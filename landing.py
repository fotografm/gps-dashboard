#!/usr/bin/env python3
"""
wifi-logger: landing page (port 80)
"""

import logging
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, os.path.dirname(__file__))
from config import LANDING_PORT, WEB_HOST, WEB_PORT, GPS_WEB_PORT, BASE_DIR

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [landing] %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)
log = logging.getLogger('landing')

app = Flask(__name__)

DB_PATH        = os.path.join(BASE_DIR, 'db', 'wifi_logger.db')
GPS_HISTORY_DB = os.path.join(BASE_DIR, 'db', 'gps_history.db')
TILES_DB       = os.path.join(BASE_DIR, 'tiles', 'tiles.mbtiles')
SKYMAP3D_PORT  = 8093


def _hostname() -> str:
    return socket.gethostname()


def _uptime() -> str:
    try:
        with open('/proc/uptime') as f:
            secs = float(f.read().split()[0])
        days  = int(secs // 86400)
        hours = int((secs % 86400) // 3600)
        mins  = int((secs % 3600) // 60)
        parts = []
        if days:  parts.append(f'{days}d')
        if hours: parts.append(f'{hours}h')
        parts.append(f'{mins}m')
        return ' '.join(parts)
    except Exception:
        return '—'


def _cpu_percent() -> str:
    try:
        result = subprocess.run(['top', '-bn1'], capture_output=True, text=True, timeout=3)
        for line in result.stdout.splitlines():
            if 'Cpu' in line or 'cpu' in line:
                parts = line.replace(',', ' ').split()
                for i, p in enumerate(parts):
                    if 'id' in p and i > 0:
                        idle = float(parts[i - 1].replace('%', ''))
                        return f'{100 - idle:.0f}%'
    except Exception:
        pass
    return '—'


def _mem_info() -> dict:
    try:
        with open('/proc/meminfo') as f:
            data = {}
            for line in f:
                k, v = line.split(':')
                data[k.strip()] = int(v.split()[0])
        total = data.get('MemTotal', 0)
        avail = data.get('MemAvailable', 0)
        used  = total - avail
        pct   = round(used / total * 100) if total else 0
        return {'total': f'{total // 1024} MB', 'used': f'{used // 1024} MB', 'pct': pct}
    except Exception:
        return {'total': '—', 'used': '—', 'pct': 0}


def _port_alive(port: int) -> bool:
    try:
        s = socket.create_connection(('127.0.0.1', port), timeout=1)
        s.close()
        return True
    except Exception:
        return False


def _human(b: int) -> str:
    if b >= 1_073_741_824: return f'{b / 1_073_741_824:.1f} GB'
    if b >= 1_048_576:     return f'{b / 1_048_576:.1f} MB'
    if b >= 1024:          return f'{b / 1024:.1f} KB'
    return f'{b} B'


def _file_size(path: str) -> int:
    try:    return os.path.getsize(path)
    except: return 0


def _db_rowcount(path: str, table: str) -> int:
    try:
        conn  = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        conn.close()
        return count
    except: return -1


def _tile_zoom_count(path: str, zoom: int) -> int:
    try:
        conn  = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        count = conn.execute(
            'SELECT COUNT(*) FROM tiles WHERE zoom_level=?', (zoom,)
        ).fetchone()[0]
        conn.close()
        return count
    except: return -1


@app.route('/')
def index():
    return render_template(
        'landing.html',
        hostname=_hostname(),
        web_port=WEB_PORT,
        gps_port=GPS_WEB_PORT,
        sky_port=SKYMAP3D_PORT,
    )


@app.route('/api/sysinfo')
def api_sysinfo():
    return jsonify({
        'hostname': _hostname(),
        'uptime':   _uptime(),
        'cpu':      _cpu_percent(),
        'mem':      _mem_info(),
        'services': {
            'wifi_logger': _port_alive(WEB_PORT),
            'gps_dash':    _port_alive(GPS_WEB_PORT),
            'skymap3d':    _port_alive(SKYMAP3D_PORT),
        },
    })


@app.route('/api/storage')
def api_storage():
    usage  = shutil.disk_usage('/')
    sd = {
        'total':   _human(usage.total),
        'used':    _human(usage.used),
        'free':    _human(usage.free),
        'pct':     round(usage.used / usage.total * 100) if usage.total else 0,
        'total_b': usage.total,
        'used_b':  usage.used,
    }
    wl_size = _file_size(DB_PATH)
    wifi_db = {
        'exists': os.path.exists(DB_PATH),
        'size':   _human(wl_size), 'size_b': wl_size,
        'aps':    _db_rowcount(DB_PATH, 'access_points'),
        'sightings': _db_rowcount(DB_PATH, 'sightings'),
    }
    gps_size = _file_size(GPS_HISTORY_DB)
    gps_db = {
        'exists': os.path.exists(GPS_HISTORY_DB),
        'size':   _human(gps_size), 'size_b': gps_size,
        'rows':   _db_rowcount(GPS_HISTORY_DB, 'sat_history'),
    }
    tile_size = _file_size(TILES_DB)
    tiles = {
        'exists': os.path.exists(TILES_DB),
        'size':   _human(tile_size), 'size_b': tile_size,
        'total':  _db_rowcount(TILES_DB, 'tiles'),
        'z14':    _tile_zoom_count(TILES_DB, 14),
        'z15':    _tile_zoom_count(TILES_DB, 15),
        'z16':    _tile_zoom_count(TILES_DB, 16),
    }
    return jsonify({'sd': sd, 'wifi_db': wifi_db, 'gps_db': gps_db, 'tiles': tiles})


@app.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    action = (request.get_json(silent=True) or {}).get('action', '')
    if action == 'reboot':
        log.info('Reboot requested')
        threading.Thread(
            target=lambda: (time.sleep(1), subprocess.run(['reboot'])), daemon=True
        ).start()
        return jsonify({'ok': True, 'action': 'reboot'})
    elif action == 'shutdown':
        log.info('Shutdown requested')
        threading.Thread(
            target=lambda: (time.sleep(1), subprocess.run(['shutdown', '-h', 'now'])), daemon=True
        ).start()
        return jsonify({'ok': True, 'action': 'shutdown'})
    return jsonify({'error': 'Invalid action'}), 400


if __name__ == '__main__':
    log.info('Landing page starting on port %d', LANDING_PORT)
    app.run(host=WEB_HOST, port=LANDING_PORT, threaded=True, debug=False)
