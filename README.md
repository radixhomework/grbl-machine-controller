# grbl-machine-controller

A GRBL CNC controller application: manual jogging, G-code job streaming,
tool-diameter-compensated probing, and Home Assistant integration via MQTT.
Designed for a Raspberry Pi, runs anywhere Python 3.9+ runs (including WSL2
for development).

See `ARCHITECTURE.md` for the design.

## Quick start (no hardware)

```bash
pip install -r requirements.txt
python -m app.main --fake
```

`--fake` runs the built-in GRBL simulator: jogging moves the DRO, probing
contacts at a simulated surface, and a streamed job runs end to end.

## Quick start (real GRBL board)

```bash
pip install -r requirements.txt
python -m app.main --port /dev/ttyUSB0
```

## Linux dependencies (WSL2 / Raspberry Pi / Debian)

```bash
sudo apt update
sudo apt install -y \
  python3 python3-pip python3-venv \
  libgl1 libegl1 libxkbcommon0 libdbus-1-3 libfontconfig1 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xfixes0 \
  libxcb-cursor0
```

The `libxcb-*` / `libgl` / `libegl` packages are what PySide6 (Qt) needs to
open a window on X11/Wayland; everything else is pure pip. On WSL2 with WSLg
(Windows 11) the UI displays out of the box; on Windows 10 use an X server
(VcXsrv) and `export DISPLAY=$(grep nameserver /etc/resolv.conf | awk '{print $2}'):0`.

Python packages: `pip install -r requirements.txt` (pyserial, PySide6,
paho-mqtt, PyYAML) — ideally inside a venv:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### USB serial in WSL2

WSL2 does not expose USB serial devices natively. Either use
[usbipd-win](https://learn.microsoft.com/en-us/windows/wsl/connect-usb)
(`usbipd bind`/`attach`, device appears as `/dev/ttyUSB0` or `/dev/ttyACM0`),
or run the app on Windows directly (`pip install -r requirements.txt`,
`python -m app.main --port COM3`).

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## MQTT / Home Assistant

Set `mqtt.enabled: true` in `config.yaml` and point it at your broker. HA
discovers the entities automatically (MQTT discovery, retained) — sensors for
status/position/RPM/progress, buttons for home/unlock/pause/resume/stop, and
number entities for feed/spindle overrides.

## systemd service (Pi deployment)

```ini
[Unit]
Description=GRBL machine controller
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/grbl-machine-controller
ExecStart=/home/pi/grbl-machine-controller/.venv/bin/python -m app.main
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
