#!/usr/bin/env bash
# gps-dashboard install.sh
# Installs the GPS Dashboard on a Raspberry Pi running Bookworm Lite (32-bit).
#
# Typical usage:
#   git clone https://github.com/fotografm/gps-dashboard.git
#   cd gps-dashboard
#   sudo bash install.sh

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
# APP_USER is the non-root user that owns and runs the dashboard services.
# Change this if your username is not "user".
APP_USER="${SUDO_USER:-user}"
INSTALL_DIR="/home/$APP_USER/gps-dashboard"
GPS_DEVICE=/dev/ttyACM0      # T-Beam USB serial — verify with: ls /dev/ttyACM* /dev/ttyUSB*

# ── Root check ────────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run as root:  sudo bash install.sh" >&2
    exit 1
fi

SRC_DIR="$(dirname "$(realpath "$0")")"

echo "=== GPS Dashboard installer ==="
echo "Source dir  : $SRC_DIR"
echo "Install dir : $INSTALL_DIR"
echo "App user    : $APP_USER"
echo "GPS device  : $GPS_DEVICE"
echo ""

# ── Verify required source files ──────────────────────────────────────────────
REQUIRED_FILES=(
    gps_web.py gps_reader.py skymap3d.py landing.py
    gps.html skymap3d.html landing.html
    requirements.txt
    gps-dashboard.service gps-landing.service gps-skymap3d.service
    99-gps-dashboard.rules
)
MISSING=0
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$SRC_DIR/$f" ]; then
        echo "ERROR: missing file: $SRC_DIR/$f" >&2
        MISSING=1
    fi
done
[ "$MISSING" -eq 1 ] && { echo "Aborting." >&2; exit 1; }
echo "All source files present."
echo ""

# ── 1. System packages ────────────────────────────────────────────────────────
echo "--- Installing system packages ---"
apt-get update -qq
apt-get install -y \
    python3 python3-venv \
    python3-gps gpsd gpsd-clients \
    curl

# ── 2. Configure gpsd ─────────────────────────────────────────────────────────
echo "--- Configuring gpsd ---"
cat > /etc/default/gpsd << GPSD_EOF
DEVICES="$GPS_DEVICE"
GPSD_OPTIONS="-n -s 115200"
START_DAEMON="true"
USBAUTO="false"
GPSD_EOF

# Delay gpsd startup so the USB hub has time to enumerate the T-Beam before
# gpsd tries to open ttyACM0.  On a Pi Zero 2W with a bus-powered hub this
# delay is critical — removing it causes gpsd to fail silently at boot.
mkdir -p /etc/systemd/system/gpsd.service.d
cat > /etc/systemd/system/gpsd.service.d/override.conf << 'OVR_EOF'
[Service]
ExecStartPre=/bin/sleep 10
OVR_EOF

systemctl enable gpsd
systemctl daemon-reload
echo "gpsd configured"

# ── 3. Create install directory ───────────────────────────────────────────────
echo "--- Creating directories ---"
mkdir -p "$INSTALL_DIR"/{templates,systemd}
chown -R "$APP_USER":"$APP_USER" "$INSTALL_DIR"

# ── 4. Copy source files ──────────────────────────────────────────────────────
echo "--- Copying source files ---"
for f in gps_web.py gps_reader.py skymap3d.py landing.py requirements.txt; do
    cp "$SRC_DIR/$f" "$INSTALL_DIR/$f"
done
cp "$SRC_DIR/gps.html"       "$INSTALL_DIR/templates/gps.html"
cp "$SRC_DIR/skymap3d.html"  "$INSTALL_DIR/templates/skymap3d.html"
cp "$SRC_DIR/landing.html"   "$INSTALL_DIR/templates/landing.html"
for svc in gps-dashboard.service gps-landing.service gps-skymap3d.service; do
    cp "$SRC_DIR/$svc" "$INSTALL_DIR/systemd/$svc"
done
chown -R "$APP_USER":"$APP_USER" "$INSTALL_DIR"
echo "Files copied"

# ── 5. Python venv ────────────────────────────────────────────────────────────
echo "--- Creating Python venv ---"
sudo -u "$APP_USER" python3 -m venv --system-site-packages "$INSTALL_DIR/venv"
sudo -u "$APP_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u "$APP_USER" "$INSTALL_DIR/venv/bin/pip" install -r "$SRC_DIR/requirements.txt" -q
echo "venv ready"

# ── 6. Install systemd service files ─────────────────────────────────────────
echo "--- Installing systemd services ---"
# Substitute the actual username into service files (replaces User=user placeholder)
for svc in gps-dashboard.service gps-landing.service gps-skymap3d.service; do
    sed "s/^User=user$/User=$APP_USER/" "$INSTALL_DIR/systemd/$svc" \
        > "/etc/systemd/system/$svc"
done
systemctl daemon-reload
systemctl enable gps-dashboard gps-landing gps-skymap3d
echo "Services installed and enabled"

# ── 7. udev rule for T-Beam hot-plug ─────────────────────────────────────────
echo "--- Installing udev rules ---"
cp "$SRC_DIR/99-gps-dashboard.rules" /etc/udev/rules.d/
udevadm control --reload-rules
echo "udev rules installed"

# ── 8. Start services ─────────────────────────────────────────────────────────
echo "--- Starting services ---"
systemctl start gpsd          || true
sleep 12   # wait for gpsd USB delay to pass before starting dashboard
systemctl start gps-dashboard || true
sleep 2
systemctl start gps-skymap3d  || true
sleep 1
systemctl start gps-landing   || true

# ── 9. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "=== Install complete ==="
echo ""
echo "Service status:"
for svc in gpsd gps-dashboard gps-skymap3d gps-landing; do
    state=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
    if [ "$state" = "active" ]; then
        printf "  %-24s running\n" "$svc"
    else
        printf "  %-24s FAILED  (journalctl -u %s)\n" "$svc" "$svc"
    fi
done

PRIMARY_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "Web interfaces:"
echo "  Landing page  : http://$PRIMARY_IP"
echo "  GPS Dashboard : http://$PRIMARY_IP:8092"
echo "  3D Skymap     : http://$PRIMARY_IP:8093"
echo ""
echo "Useful commands:"
echo "  cgps -s                       (live GPS fix status)"
echo "  journalctl -fu gps-dashboard"
echo "  journalctl -fu gps-skymap3d"
echo "  journalctl -fu gpsd"
echo ""
echo "IMPORTANT — USB power:"
echo "  Do NOT hot-plug the T-Beam GPS on a bus-powered hub."
echo "  Always plug it in before powering the Pi, or use a powered hub."
echo "  See README.md for details."
