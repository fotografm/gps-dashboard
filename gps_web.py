#!/usr/bin/env python3
"""
wifi-logger: GPS dashboard (port 8092)
Features:
  - Reads TPV + SKY reports from gpsd (shares with scanner.py)
  - 24-hour satellite history sampled every 30 seconds
  - History persisted to SQLite — survives service restarts and Pi reboots
  - Loaded back into RAM on startup so graphs are immediately populated
  - /api/gps         — current position, satellites, DOP, Maidenhead
  - /api/gps_history — 24h history per PRN for skyplot/graphs
  - /api/shutdown    — reboot or shutdown the Pi
Port: 8092
"""

import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, os.path.dirname(__file__))
from config import GPS_HOST, GPS_PORT, GPS_WEB_PORT, WEB_HOST, BASE_DIR

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [gps-web] %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)
log = logging.getLogger('gps_web')

# ── History database path ─────────────────────────────────────────────────────
HISTORY_DB    = os.path.join(BASE_DIR, 'db', 'gps_history.db')
HISTORY_INTERVAL = 30       # seconds between samples
HISTORY_MAXAGE   = 86400    # 24 hours

# ── Shared GPS state ──────────────────────────────────────────────────────────
_lock = threading.Lock()
_stop = threading.Event()

_position = {
    'lat': None, 'lon': None, 'alt': None, 'speed': None,
    'fix': False, 'mode': 0,
}
_sky = {
    'hdop': None, 'vdop': None, 'pdop': None, 'satellites': [],
}

# ── In-memory satellite history ───────────────────────────────────────────────
# {prn_str: [[unix_ts, az, el, ss], ...]}
_history: Dict[str, List] = {}
_history_lock = threading.Lock()


# ── SQLite history DB ─────────────────────────────────────────────────────────
def _init_history_db() -> None:
    os.makedirs(os.path.dirname(HISTORY_DB), exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sat_history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            prn       TEXT    NOT NULL,
            ts        REAL    NOT NULL,
            az        REAL    NOT NULL,
            el        REAL    NOT NULL,
            ss        REAL    NOT NULL
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sh_ts  ON sat_history(ts)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sh_prn ON sat_history(prn, ts)')
    conn.commit()
    conn.close()
    log.info('History DB ready: %s', HISTORY_DB)


def _load_history_from_db() -> None:
    """Load last 24 h of satellite history from DB into _history on startup."""
    cutoff = time.time() - HISTORY_MAXAGE
    try:
        conn = sqlite3.connect(HISTORY_DB)
        rows = conn.execute(
            'SELECT prn, ts, az, el, ss FROM sat_history WHERE ts >= ? ORDER BY ts ASC',
            (cutoff,),
        ).fetchall()
        conn.close()
        with _history_lock:
            for prn, ts, az, el, ss in rows:
                if prn not in _history:
                    _history[prn] = []
                _history[prn].append([ts, az, el, ss])
        log.info('Loaded %d history rows from DB (%d PRNs)', len(rows), len(_history))
    except Exception as exc:
        log.warning('Failed to load history from DB: %s', exc)


def _write_history_to_db(new_points: List) -> None:
    """Write new points to DB and prune rows older than 24 h."""
    cutoff = time.time() - HISTORY_MAXAGE
    try:
        conn = sqlite3.connect(HISTORY_DB)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executemany(
            'INSERT INTO sat_history (prn, ts, az, el, ss) VALUES (?,?,?,?,?)',
            new_points,
        )
        conn.execute('DELETE FROM sat_history WHERE ts < ?', (cutoff,))
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning('DB write error: %s', exc)


# ── gpsd reader thread ────────────────────────────────────────────────────────
def _gps_thread() -> None:
    while not _stop.is_set():
        try:
            import gps as gpsd_mod
            session = gpsd_mod.gps(
                host=GPS_HOST, port=GPS_PORT,
                mode=gpsd_mod.WATCH_ENABLE | gpsd_mod.WATCH_NEWSTYLE,
            )
            log.info('GPS reader connected to gpsd %s:%d', GPS_HOST, GPS_PORT)
            for report in session:
                if _stop.is_set():
                    return
                cls = report.get('class')
                if cls == 'TPV':
                    mode = int(getattr(report, 'mode', 0))
                    with _lock:
                        _position.update({
                            'lat':   getattr(report, 'lat',   None),
                            'lon':   getattr(report, 'lon',   None),
                            'alt':   getattr(report, 'alt',   None),
                            'speed': getattr(report, 'speed', None),
                            'fix':   mode >= 2,
                            'mode':  mode,
                        })
                elif cls == 'SKY':
                    sats_raw = getattr(report, 'satellites', []) or []
                    sats = []
                    for s in sats_raw:
                        sats.append({
                            'prn':  getattr(s, 'PRN',  None),
                            'el':   getattr(s, 'el',   None),
                            'az':   getattr(s, 'az',   None),
                            'ss':   getattr(s, 'ss',   None),
                            'used': bool(getattr(s, 'used', False)),
                        })
                    with _lock:
                        _sky.update({
                            'hdop':       getattr(report, 'hdop', None),
                            'vdop':       getattr(report, 'vdop', None),
                            'pdop':       getattr(report, 'pdop', None),
                            'satellites': sats,
                        })
        except Exception as exc:
            log.warning('gpsd error: %s — retrying in 5s', exc)
            with _lock:
                _position['fix']   = False
                _sky['satellites'] = []
            time.sleep(5)


# ── History sampler thread ────────────────────────────────────────────────────
def _history_thread() -> None:
    while not _stop.is_set():
        time.sleep(HISTORY_INTERVAL)
        now    = time.time()
        cutoff = now - HISTORY_MAXAGE

        with _lock:
            sats = list(_sky['satellites'])

        new_db_rows = []
        with _history_lock:
            for s in sats:
                prn = s.get('prn')
                az  = s.get('az')
                el  = s.get('el')
                ss  = s.get('ss')
                if prn is None or az is None or el is None:
                    continue
                key = str(prn)
                pt  = [now, az, el, ss if ss is not None else 0]
                if key not in _history:
                    _history[key] = []
                _history[key].append(pt)
                new_db_rows.append((key, now, az, el, ss if ss is not None else 0))

            # Prune old entries from RAM
            for key in list(_history.keys()):
                _history[key] = [p for p in _history[key] if p[0] >= cutoff]
                if not _history[key]:
                    del _history[key]

        # Write new points and prune DB (outside the history lock)
        if new_db_rows:
            _write_history_to_db(new_db_rows)


# ── Maidenhead ────────────────────────────────────────────────────────────────
def _maidenhead(lat: float, lon: float) -> str:
    try:
        lat += 90.0; lon += 180.0
        a = chr(ord('A') + int(lon / 20))
        b = chr(ord('A') + int(lat / 10))
        c = str(int((lon % 20) / 2))
        d = str(int(lat % 10))
        e = chr(ord('a') + int((lon % 2) * 12))
        f = chr(ord('a') + int((lat % 1) * 24))
        return a + b + c + d + e + f
    except Exception:
        return '——'


# ── Flask ─────────────────────────────────────────────────────────────────────
app = Flask(__name__)


@app.route('/')
def index():
    return render_template('gps.html')


@app.route('/api/gps')
def api_gps():
    with _lock:
        pos  = dict(_position)
        sky  = dict(_sky)
        sats = list(sky['satellites'])

    maidenhead = None
    if pos['lat'] is not None and pos['lon'] is not None:
        maidenhead = _maidenhead(pos['lat'], pos['lon'])

    sats_sorted = sorted(sats, key=lambda s: (not s['used'], -(s['ss'] or 0)))

    return jsonify({
        'position': pos,
        'sky': {
            'hdop':       _fmtf(sky['hdop']),
            'vdop':       _fmtf(sky['vdop']),
            'pdop':       _fmtf(sky['pdop']),
            'satellites': sats_sorted,
            'sat_count':  len(sats),
            'used_count': sum(1 for s in sats if s['used']),
        },
        'maidenhead': maidenhead,
    })


@app.route('/api/gps_history')
def api_gps_history():
    """
    Returns satellite history for skyplot/graphs.
    Each PRN maps to [[age_seconds, az, el, ss], ...] where age=0 is now.
    Served from RAM — no DB hit per request.
    """
    now = time.time()
    with _history_lock:
        out = {
            prn: [[round(now - p[0]), p[1], p[2], p[3]] for p in pts]
            for prn, pts in _history.items()
        }
    return jsonify(out)


@app.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    action = (request.get_json(silent=True) or {}).get('action', '')
    if action == 'reboot':
        log.info('Reboot requested via GPS dashboard')
        threading.Thread(
            target=lambda: (time.sleep(1), subprocess.run(['sudo', 'reboot'])),
            daemon=True,
        ).start()
        return jsonify({'ok': True, 'action': 'reboot'})
    elif action == 'shutdown':
        log.info('Shutdown requested via GPS dashboard')
        threading.Thread(
            target=lambda: (time.sleep(1), subprocess.run(['sudo', 'shutdown', '-h', 'now'])),
            daemon=True,
        ).start()
        return jsonify({'ok': True, 'action': 'shutdown'})
    return jsonify({'error': 'Invalid action'}), 400


def _fmtf(v) -> Optional[str]:
    return f'{v:.1f}' if v is not None else None


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    _init_history_db()
    _load_history_from_db()     # immediately populate from SD card

    threading.Thread(target=_gps_thread,     daemon=True, name='gps-reader').start()
    threading.Thread(target=_history_thread, daemon=True, name='gps-history').start()

    log.info('GPS dashboard starting on port %d', GPS_WEB_PORT)
    app.run(host=WEB_HOST, port=GPS_WEB_PORT, threaded=True, debug=False)
