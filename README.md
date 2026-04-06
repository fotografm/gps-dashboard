# gps-dashboard

A GPS dashboard for the Raspberry Pi Zero 2W using a T-Beam v1.2 as a GPS
source via USB serial (NMEA at 115200 baud). Displays live satellite positions,
signal strength, sky map with orbital trails, 3D skymap, DOP values, Maidenhead
grid locator, and an OpenStreetMap embed. Built with Python, Flask, and gpsd.

## Hardware

| Component | Notes |
|---|---|
| Raspberry Pi Zero 2W | Bookworm Lite 32-bit |
| T-Beam v1.2 | GPS source via USB serial (ttyACM0), NMEA at 115200 baud |
| USB hub HAT | 4-port, bus-powered or externally powered — see USB power warning below |
| USB ethernet adapter | For LAN access and SSH |

## Web interfaces

| URL | Description |
|---|---|
| `http://<ip>` | Landing page |
| `http://<ip>:8092` | GPS Dashboard — satellites, SNR, DOP, grid, map |
| `http://<ip>:8093` | 3D Skymap — orbital trails in three dimensions |

## Installation

```bash
git clone https://github.com/fotografm/gps-dashboard.git
cd gps-dashboard
sudo bash install.sh
```

The installer auto-detects your username via `$SUDO_USER`. If your username
is not `user`, the service files are patched automatically. No manual editing
required.

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

The following are intentionally not included:

- GPS history database (`gps_history.db`)
- Any logged position data
- WiFi AP scanner and logger (separate project)

## Licence

MIT
