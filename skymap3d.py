#!/usr/bin/env python3
"""
wifi-logger: 3D satellite skymap (port 8093)
Serves the Three.js 3D visualisation page.
Proxies /api/gps and /api/gps_history from gps_web.py (port 8092)
so the browser only ever talks to one origin.
"""

import logging
import os
import sys

import requests
from flask import Flask, jsonify, render_template

sys.path.insert(0, os.path.dirname(__file__))
from config import WEB_HOST

SKYMAP3D_PORT = 8093
GPS_API_BASE  = 'http://127.0.0.1:8092'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [skymap3d] %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)
log = logging.getLogger('skymap3d')

app = Flask(__name__)


@app.route('/')
def index():
    return render_template('skymap3d.html')


@app.route('/api/gps')
def proxy_gps():
    try:
        r = requests.get(f'{GPS_API_BASE}/api/gps', timeout=3)
        return jsonify(r.json())
    except Exception as exc:
        log.warning('GPS proxy error: %s', exc)
        return jsonify({'error': 'GPS service unavailable'}), 503


@app.route('/api/gps_history')
def proxy_history():
    try:
        r = requests.get(f'{GPS_API_BASE}/api/gps_history', timeout=5)
        return jsonify(r.json())
    except Exception as exc:
        log.warning('History proxy error: %s', exc)
        return jsonify({}), 503


if __name__ == '__main__':
    log.info('3D Skymap starting on port %d', SKYMAP3D_PORT)
    app.run(host=WEB_HOST, port=SKYMAP3D_PORT, threaded=True, debug=False)
