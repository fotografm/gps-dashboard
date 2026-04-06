# gps-dashboard

A GPS dashboard for the Raspberry Pi Zero 2W using a T-Beam v1.2 as a GPS
source via USB serial (NMEA at 115200 baud). Displays live satellite positions,
signal strength, sky map with orbital trails, 3D skymap, DOP values, Maidenhead
grid locator, and an OpenStreetMap embed. Built with Python, Flask, and gpsd.

> **GPS hardware note:** The T-Beam v1.2 is the currently tested and supported
> GPS source. Support for additional GPS devices will be added and released as
> testing is completed.

---

## Hardware required

| Component | Notes |
|---|---|
| Raspberry Pi Zero 2W | Bookworm Lite 32-bit — see OS setup below |
| T-Beam v1.2 | Flashed with `tbeam_gps_passthrough` sketch — see below |
| USB hub HAT | 4-port — see USB power warning before choosing bus-powered vs powered |
| USB ethernet adapter | Required for LAN/SSH access during setup |
| MicroSD card | 8 GB minimum, 16 GB recommended |
| 5V/2.5A USB power supply | Micro-USB, quality PSU only — cheap supplies cause instability |

---

## Raspberry Pi OS setup (headless)

Use **Raspberry Pi Imager** to write **Bookworm Lite 32-bit** to the SD card.
In the Imager settings (click the gear icon) before writing:

- Set hostname (e.g. `raspi50`)
- Enable SSH, set username and password
- Configure WiFi **only if needed for initial setup** — ethernet is preferred
- Set locale and WiFi country to match your region (e.g. `DE` for Germany)

> **Do not use Trixie (Debian 13)** — it has known issues with headless
> WiFi and SSH setup via Raspberry Pi Imager. Bookworm (Debian 12) only.

Boot the Pi with the ethernet adapter plugged in, find its IP on your router,
then SSH in to proceed with installation.

---

## Installation

```bash
git clone https://github.com/fotografm/gps-dashboard.git
cd gps-dashboard
sudo bash install.sh
```

The installer auto-detects your username via `$SUDO_USER`. If your username
differs from `user`, service files are patched automatically — no manual
editing required.

---

## Accessing the dashboard

### Via LAN (ethernet)

The Pi gets a DHCP address from your router on the ethernet adapter. Find the
IP from your router's DHCP table or use:

```bash
hostname -I
```

Then open a browser on any device on the same network:

| URL | Description |
|---|---|
| `http://<ip>` | Landing page |
| `http://<ip>:8092` | GPS Dashboard — satellites, SNR, DOP, grid, map |
| `http://<ip>:8093` | 3D Skymap — orbital trails in three dimensions |

### Via WiFi hotspot

The Pi creates a WiFi hotspot using its onboard `wlan0` adapter. Connect
any phone, tablet, or laptop to the hotspot and point a browser at the
gateway address:

| Setting | Value |
|---|---|
| SSID | hostname of the Pi (e.g. `raspi50`) |
| Password | `reticulum` |
| Gateway / landing page | `http://10.42.0.1` |
| GPS Dashboard | `http://10.42.0.1:8092` |
| 3D Skymap | `http://10.42.0.1:8093` |

> The hotspot uses the Pi's onboard WiFi chip (2.4 GHz only). It hands out
> DHCP leases in the range `10.42.0.10`–`10.42.0.50`. No internet access is
> provided via the hotspot — it is a local-only access point.

---

## T-Beam GPS passthrough sketch

The T-Beam v1.2 must be flashed with the included Arduino sketch before use.
The sketch powers the GPS module via the AXP2101 PMU, enables all NMEA
sentences (GGA, GLL, GSA, GSV, RMC, VTG), and relays them to USB serial at
115200 baud. The T-Beam display is not used and does not need to be working.

Works with both NEO-6M and NEO-M8N GPS variants on the T-Beam v1.2.

### Compile with arduino-cli (no IDE required)

Install arduino-cli to `~/bin`:

```bash
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
echo 'export PATH=$PATH:~/bin' >> ~/.bashrc && source ~/.bashrc
```

Add ESP32 board support:

```bash
arduino-cli config init
arduino-cli config add board_manager.additional_urls \
    https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

Compile the sketch:

```bash
mkdir -p ~/tbeam_gps_passthrough
cp tbeam_gps_passthrough/tbeam_gps_passthrough.ino ~/tbeam_gps_passthrough/
arduino-cli compile --fqbn esp32:esp32:ttgo-t1 ~/tbeam_gps_passthrough --export-binaries
```

The compiled binary will be at:

```
~/tbeam_gps_passthrough/build/esp32.esp32.ttgo-t1/tbeam_gps_passthrough.ino.merged.bin
```

### Flash with Spacehuhn ESPWebTool (no drivers required)

Requires Chrome or Chromium — Firefox does not support WebSerial.

1. Connect the T-Beam to your desktop via USB
2. Open **https://esptool.spacehuhn.com** in Chrome/Chromium
3. Delete all rows in the flash table except one
4. Set the remaining row's offset to `0`
5. Click **Choose file** and select `tbeam_gps_passthrough.ino.merged.bin`
6. Click **Program** and wait for completion
7. Unplug from the desktop and connect to the Pi's USB hub

### Verify after flashing (optional, from desktop)

```bash
arduino-cli monitor -p /dev/ttyACM0 -c baudrate=115200
```

You should see clean NMEA sentences (`$GPRMC`, `$GPGGA`, `$GPGSV` etc.)
after the initial ESP32 boot ROM garbage characters. No fix indoors is
normal — `$GPRMC,,V,` means waiting for satellite acquisition.

---

## USB power and boot sequence — critical notes

### Bus-powered hub brownout risk (Pi Zero 2W)

The Pi Zero 2W has a single USB OTG port shared by all attached devices. A
bus-powered hub draws all device power from this port. The T-Beam draws a
significant current spike during USB enumeration. Combined with an ethernet
adapter this can exceed what the Pi can supply, causing a **brownout and
system freeze**.

**Rules to avoid brownout on a Pi Zero 2W with a bus-powered hub:**

- Always plug the T-Beam in **before** powering the Pi. Cold-plug at boot
  spreads enumeration across the boot sequence and is safe.
- Never hot-plug the T-Beam while the Pi is running on a bus-powered hub.
- A powered USB hub (with its own PSU, 5V/2A minimum) eliminates this
  constraint entirely and is strongly recommended for permanent installations.
- A Raspberry Pi 4B is not affected — its onboard USB controller has a
  separate power budget and handles hot-plug safely with a good 3A PSU.

### gpsd startup delay

gpsd is configured with a 10-second `ExecStartPre=/bin/sleep 10` delay. This
gives the USB hub time to fully enumerate all attached devices before gpsd
attempts to open `/dev/ttyACM0`. Removing this delay causes gpsd to fail
silently at boot when the T-Beam has not yet appeared in `/dev`.

### Service startup order

Services start in this strict order after the delay:

```
gpsd  (waits 10 s for USB enumeration)
  └─ gps-dashboard  (waits for gpsd)
       └─ gps-skymap3d
            └─ gps-landing
```

This staggered order prevents any service from racing to connect to gpsd
before it is ready.

---

## Hot-plug hardening

A udev rule (`99-gps-dashboard.rules`) is installed to `/etc/udev/rules.d/`.
It watches for the T-Beam's TTY device and automatically restarts gpsd when
the device is plugged in at runtime:

```
ACTION=="add", SUBSYSTEM=="tty", KERNEL=="ttyACM0",
    RUN+="/bin/systemctl restart gpsd.service"
```

Behaviour with this rule in place:

- **T-Beam unplugged while running** — gpsd logs an error and waits. The
  dashboard continues serving the last known data.
- **T-Beam plugged back in** — udev restarts gpsd automatically within
  seconds. No manual intervention needed.
- **T-Beam absent at boot** — gpsd starts, finds no device, and retries
  quietly in the background. When the T-Beam appears, udev fires the restart.
- **Hot-plug on bus-powered hub** — do not do this on a Pi Zero 2W. See
  brownout warning above.

---

## Services

| Service | Runs as | Port | Description |
|---|---|---|---|
| `gpsd` | root | 2947 | GPS daemon, reads T-Beam NMEA at 115200 baud |
| `gps-dashboard` | user | 8092 | Flask GPS web server |
| `gps-skymap3d` | user | 8093 | 3D skymap server |
| `gps-landing` | root | 80 | Landing page (root required for port 80) |

```bash
# Check all service status
systemctl status gpsd gps-dashboard gps-skymap3d gps-landing

# Live logs
journalctl -fu gps-dashboard
journalctl -fu gpsd

# GPS fix status in terminal
cgps -s
```

---

## Useful diagnostic commands

```bash
# Check what's on the USB bus
lsusb

# Verify T-Beam is visible as a serial device
ls /dev/ttyACM*

# Watch raw NMEA output from T-Beam
cat /dev/ttyACM0

# Check gpsd is receiving data
gpspipe -w | head -20

# Check IP addresses on all interfaces
ip addr show
```

---

## Files not included in this repo

- GPS history database (`gps_history.db`) — created automatically on first run
- Any logged position data
- WiFi AP scanner and logger (separate project)

---

## Licence

MIT
