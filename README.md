# gps-dashboard

A GPS dashboard for the Raspberry Pi Zero 2W using a T-Beam v1.2 as a GPS
source via USB serial (NMEA at 115200 baud). Displays live satellite positions,
signal strength, sky map with orbital trails, 3D skymap, DOP values, Maidenhead
grid locator, and an OpenStreetMap embed. Built with Python, Flask, and gpsd.

> **GPS hardware note:** The T-Beam v1.2 is the currently tested and supported
> GPS source. Support for additional GPS devices will be added and released as
> testing is completed.

## Hardware

| Component | Notes |
|---|---|
| Raspberry Pi Zero 2W | Bookworm Lite 32-bit |
| T-Beam v1.2 | Flashed with `tbeam_gps_passthrough` sketch — see below |
| USB hub HAT | 4-port, bus-powered or externally powered — see USB power warning |
| USB ethernet adapter | For LAN access and SSH |

## Web interfaces

| URL | Description |
|---|---|
| `http://<ip>` | Landing page |
| `http://<ip>:8092` | GPS Dashboard — satellites, SNR, DOP, grid, map |
| `http://<ip>:8093` | 3D Skymap — orbital trails in three dimensions |

## T-Beam GPS passthrough sketch

The T-Beam v1.2 must be flashed with the included Arduino sketch before use.
The sketch powers the GPS module via the AXP2101 PMU, enables all NMEA
sentences (GGA, GLL, GSA, GSV, RMC, VTG), and relays them to USB serial at
115200 baud. The display is not used and does not need to be working.

Works with both NEO-6M and NEO-M8N GPS variants on the T-Beam v1.2.

### Compile with arduino-cli (no IDE required)

Install arduino-cli:

```bash
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
```

Add to PATH permanently:

```bash
echo 'export PATH=$PATH:~/bin' >> ~/.bashrc && source ~/.bashrc
```

Add ESP32 board support and compile:

```bash
arduino-cli config init
arduino-cli config add board_manager.additional_urls \
    https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

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

1. Connect the T-Beam via USB
2. Open **https://esptool.spacehuhn.com** in Chrome/Chromium
3. Delete all rows except one
4. Set the offset to `0`
5. Click **Choose file** and select `tbeam_gps_passthrough.ino.merged.bin`
6. Click **Program**

### Verify after flashing

```bash
arduino-cli monitor -p /dev/ttyACM0 -c baudrate=115200
```

You should see clean NMEA sentences (`$GPRMC`, `$GPGGA`, `$GPGSV` etc.)
after the initial ESP32 boot ROM garbage characters. No fix is shown indoors —
`$GPRMC,,V,` is normal until the T-Beam has a sky view.

## Installation

```bash
git clone https://github.com/fotografm/gps-dashboard.git
cd gps-dashboard
sudo bash install.sh
```

The installer auto-detects your username via `$SUDO_USER`. If your username
is not `user`, the service files are patched automatically.

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

Services start in this order after the delay:

```
gpsd  (waits 10 s for USB enumeration)
  └─ gps-dashboard  (waits for gpsd)
       └─ gps-skymap3d
            └─ gps-landing
```

This staggered order prevents any service from racing to connect to gpsd
before it is ready.

## Hot-plug hardening

A udev rule (`99-gps-dashboard.rules`) is installed to `/etc/udev/rules.d/`.
It watches for the T-Beam's TTY device and automatically restarts gpsd when
the device is plugged in at runtime:

```
ACTION=="add", SUBSYSTEM=="tty", KERNEL=="ttyACM0",
    RUN+="/bin/systemctl restart gpsd.service"
```

This means:

- **T-Beam unplugged while running** — gpsd logs an error and waits. The
  dashboard continues serving the last known data.
- **T-Beam plugged back in** — udev restarts gpsd automatically within
  seconds. No manual intervention needed.
- **T-Beam absent at boot** — gpsd starts, finds no device, and retries
  quietly in the background. When the T-Beam appears, udev fires the restart.

## Services

| Service | Description |
|---|---|
| `gpsd` | GPS daemon, reads T-Beam NMEA at 115200 baud |
| `gps-dashboard` | Flask web server, port 8092 |
| `gps-skymap3d` | 3D skymap server, port 8093 |
| `gps-landing` | Landing page, port 80 (runs as root for privileged port) |

```bash
# Check status
systemctl status gpsd gps-dashboard gps-skymap3d gps-landing

# Live logs
journalctl -fu gps-dashboard
journalctl -fu gpsd

# GPS fix status
cgps -s
```

## Files excluded from this repo

- GPS history database (`gps_history.db`)
- Any logged position data

## Licence

MIT
