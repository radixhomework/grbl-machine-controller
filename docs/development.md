# Development

## Code layout

```
app/
├── core/                     # Qt-free core (unit-testable without a GUI)
│   ├── state.py              # observable MachineState — single source of truth
│   ├── serial_transport.py   # pyserial transport + in-memory FakeTransport
│   ├── grbl_adapter.py       # GRBL protocol: parsing, real-time bytes, command API
│   ├── gcode_streamer.py     # character-counting flow control (128-byte buffer)
│   ├── job_manager.py        # job state machine (Idle/Running/Paused/Alarm/…)
│   ├── probe.py              # probe sequences + compensation math
│   └── fake_grbl.py          # GRBL simulator (no hardware needed)
├── ha/mqtt_bridge.py         # Home Assistant discovery + state mirroring
├── ui/                       # PySide6 widgets; UI never touches serial directly
│   ├── dashboard.py          # the all-in-one screen
│   ├── preview3d.py          # software-rendered 3D toolpath (no OpenGL)
│   ├── preferences.py        # settings dialog
│   └── bridge.py             # forwards MachineState updates to the Qt loop
├── main_window.py            # window, menu bar, status bar
└── main.py                   # entry point / wiring
```

Design rule: the **core** never imports Qt. Everything the UI shows comes
from `MachineState` subscriptions, and every command goes through
`GRBLAdapter` or `JobManager`.

## The GRBL simulator

`app/core/fake_grbl.py` implements enough of the GRBL 1.1 protocol to run
the whole app offline:

```bash
python -m app.main --fake
```

It handles status reports (`<Idle|MPos:...|FS:...|Ov:...>`), `ok`/`error`
acks, `$J=` jogs with real-time cancel, animated motion, `G38.2` probe
reports (`[PRB:x,y,z:1]`), `G10 L2/L20` offsets, alarms, and soft reset.
New protocol features should be added there first, then covered by a test.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Coverage focus: streamer flow control (buffer limits, ordering, error abort,
pause), GRBL parsing and command API (against the simulator), probe
compensation math, `MachineState` observability, and job lifecycle
including alarm recovery.

## Conventions

- Real-time single-byte commands (`?`, `!`, `~`, 0x18, 0x85) bypass all
  queueing; buffered commands always wait for their `ok`/`error`.
- The streamer may hold up to (128 − 2) in-flight bytes; a line is only sent
  if it fits.
- UI state changes cross threads via the `StateBridge` signal, never by
  touching widgets from core threads.

## Deploying on a Raspberry Pi

Install, then run as a systemd service:

```ini
# /etc/systemd/system/grbl-machine-controller.service
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

```bash
sudo systemctl enable --now grbl-machine-controller
```

Linux runtime dependencies (Debian/Raspberry Pi OS):

```bash
sudo apt install -y libgl1 libegl1 libxkbcommon0 libdbus-1-3 libfontconfig1 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xfixes0 \
  libxcb-cursor0
```

## Known limitations (v1)

- GRBL only, USB serial only (by design).
- One machine per instance.
- One-off MDI commands sent *while* a job streams share the streamer's ack
  channel and can confuse its bookkeeping — avoid MDI during a run.
