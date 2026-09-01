# CNCPi — Architecture

## 1. Overview

CNCPi is a GRBL-based CNC controller application, designed to run on a Raspberry Pi and communicate with a GRBL controller board over USB serial. It provides manual jogging, G-code job streaming, XY/corner probing with tool-diameter compensation, and Home Assistant integration via MQTT.

**Scope constraints (by design):**
- Communication protocol: **GRBL** only (no Marlin/LinuxCNC support in v1).
- Connection: **USB serial** only.
- Motion planning/interpolation is done entirely by GRBL firmware; CNCPi is a streamer/supervisor, not a real-time motion controller.
- Runs as a local appliance on a Raspberry Pi, with a touchscreen/desktop UI and headless MQTT control.

## 2. Goals & Non-Goals

**Goals**
- Expose every GRBL real-time and administrative command through a clean API and UI (jog, home, spindle, overrides, hold/resume, probing, work coordinate systems).
- Stream G-code files reliably without starving or overflowing GRBL's serial RX buffer.
- Provide accurate XY edge/corner probing that compensates for tool diameter.
- Integrate with Home Assistant with near-zero HA-side maintenance.
- Be simple to build, deploy, and update on a Raspberry Pi.

**Non-Goals (v1)**
- Support for firmware other than GRBL.
- Software-based real-time step generation (no LinuxCNC-style hard real-time).
- Network/Ethernet controller connections.
- Multi-machine management from a single instance.

## 3. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         UI (PySide6)                          │
│  Jog Panel │ G-code Console │ Toolpath View │ Probe Wizard    │
└───────────────────────────┬────────────────────────────────┘
                             │ signals/slots (Qt)
┌───────────────────────────▼────────────────────────────────┐
│                        Core (Python)                          │
│                                                                 │
│  ┌───────────┐   ┌────────────┐   ┌──────────────┐          │
│  │ JobManager │──▶│GCodeStreamer│──▶│ GRBLAdapter  │          │
│  └───────────┘   └────────────┘   └──────┬───────┘          │
│                                            │                   │
│  ┌───────────┐   ┌────────────┐          │                   │
│  │  Probe    │──▶│MachineState │◀─────────┘                   │
│  │ (state    │   │(observable) │                              │
│  │ machine)  │   └──────┬─────┘                                │
│  └───────────┘          │                                     │
└──────────────────────────┼──────────────────────────────────┘
                            │                          ┌─────────────┐
┌───────────────────────────▼────────────────┐  │  MQTT Bridge │
│           SerialTransport (pyserial)         │  │ (HA discovery)│
└───────────────────────────┬──────────────────┘  └──────┬──────┘
                             │ USB Serial                    │ MQTT
                        ┌────▼─────┐                   ┌─────▼─────┐
                        │  GRBL    │                   │  MQTT     │
                        │  board   │                   │  Broker   │
                        └──────────┘                   │(user's HA)│
                                                          └───────────┘
```

## 4. Component Breakdown

### 4.1 `core/serial_transport.py`
Raw serial connection management: open/close, baud rate, reconnect-on-disconnect, byte-level read/write. No GRBL-specific logic. Runs its own read thread, pushing raw lines into a queue consumed by `GRBLAdapter`.

### 4.2 `core/grbl_adapter.py`
Translates generic commands into GRBL's dialect and parses GRBL's responses.
- Sends real-time single-byte commands (`?`, `!`, `~`, soft reset `0x18`, jog-cancel `0x85`) immediately, bypassing any queue.
- Sends buffered commands (G-code lines, `$` settings, `G10`, jog `$J=`) through the streamer's flow control.
- Parses status reports (`<Idle|MPos:...|FS:...|Ov:...>`) and probe reports (`[PRB:x,y,z:1]`) into `MachineState`.
- Polls status on a timer (~150ms) unless GRBL auto-report is enabled.

### 4.3 `core/gcode_streamer.py`
Implements **character-counting flow control** against GRBL's 128-byte RX buffer: tracks bytes sent per line, only sends the next line once buffer headroom is confirmed via received `ok`/`error` acknowledgments. Prevents both buffer overflow and planner starvation (which causes stuttery motion).

### 4.4 `core/job_manager.py`
Job-level state machine: `Idle → Running → Paused (Hold) → Alarm → Error → Complete`. Owns file loading, start/pause/resume/stop, progress tracking, and reacts to `MachineState` transitions (e.g., GRBL alarm halts the job and surfaces an error to the UI).

### 4.5 `core/state.py`
Observable `MachineState` object: machine position, work position, active WCS, feed/spindle overrides, spindle RPM, alarm/error codes, limit switch states, buffer state. UI and MQTT bridge subscribe to changes; this is the single source of truth for "what is the machine doing right now."

### 4.6 `core/probe.py`
Explicit state machine for probing routines (not a linear script), handling fast-probe → retract → slow-probe → compute → apply-offset, plus failure paths (no contact, user cancel). See §6 for the compensation algorithm.

### 4.7 `ha/mqtt_bridge.py`
Publishes Home Assistant MQTT Discovery messages on startup (retained, so HA picks them up automatically — no custom HA component required) and mirrors `MachineState` to MQTT topics. Subscribes to a command topic to relay HA-side button/number changes back into `JobManager`/`GRBLAdapter`. See §7.

### 4.8 `ui/*`
PySide6 views: jog panel, G-code console/file loader, 2D/3D toolpath preview, probe wizard, settings editor. All UI state derives from `MachineState`/`JobManager` via Qt signals — the UI never talks to serial directly.

## 5. Command API (Core → GRBL abstraction)

The core exposes a unified command surface so UI and MQTT both call the same functions:

```
jog(axis, distance, feedrate)
moveAbsolute(x, y, z, feedrate)
homeAll() / homeAxis(axis)
setSpindleSpeed(rpm); spindleOn(direction); spindleOff()
startProbe(axis, direction, feedrate) -> probed position
setWorkOffset(wcs, x, y, z)                # G54-G59 via G10 L20
setFeedOverride(pct); setSpindleOverride(pct); setRapidOverride(pct)
hold() / resume() / reset() / unlock()
runMacro(name)
```

## 6. XY Probing with Tool Diameter Compensation

GRBL's `G38.2` reports the position of the **tool center** at the moment of contact, not the true workpiece edge. CNCPi corrects for this using the tool's radius from a tool table.

**Routine (single edge):**
1. User jogs near the edge and specifies approach direction and active tool.
2. Fast probe: `G38.2` toward the edge at a fast feedrate until contact.
3. Retract a small fixed distance away from the surface.
4. Slow re-probe at reduced feedrate for accuracy.
5. Parse `[PRB:x,y,z:1]` from GRBL for the confirmed contact position.
6. Compute true edge: `true_pos = probed_pos - (tool_radius * approach_sign)`, where `approach_sign` is derived from the specified approach direction.
7. Apply via `G10 L20 P<wcs> <axis><true_pos>` to zero the active work coordinate system at the true edge.

**Corner-finding** runs this routine on two perpendicular faces sequentially, optionally followed by a Z-touch probe, to zero X, Y, and Z in one wizard flow.

Tool radius is looked up from a simple tool table (JSON/SQLite, keyed by tool number) so the compensation is automatic once the active tool is selected.

## 7. Home Assistant Integration (MQTT Discovery)

CNCPi integrates with Home Assistant as a plain MQTT client — **no custom HA integration/component is written or maintained**. This is a deliberate simplification: HA's built-in MQTT integration auto-creates entities from retained discovery payloads.

- **Entities published** (`homeassistant/<component>/cncpi/<id>/config`):
  - `sensor`: machine status, X/Y/Z position, spindle RPM, feed rate, job progress %
  - `binary_sensor`: job running, alarm active, limit switch triggered
  - `button`: Home, Unlock/Reset, Pause, Resume, Stop
  - `number`: feed override %, spindle override % (writable)
- **State updates**: published on `MachineState` change, throttled to ~1 Hz.
- **Commands from HA**: subscribed on `cncpi/cmd/#`, routed into the core command API.
- **Requirement**: user must have an MQTT broker already configured in Home Assistant; CNCPi just needs broker host/credentials in `config.yaml`.

This gives dashboard cards, automations, and notifications with roughly 150–200 lines of bridge code and zero HA-side deployment.

## 8. Deployment & CI

- **Packaging**: PyInstaller one-file build, or (preferred for this appliance-style use case) a `pip`-installable package run as a **systemd service**, updated via `git pull && pip install -e .`. The systemd route avoids ARM/Qt packaging fragility that PyInstaller can hit on Raspberry Pi OS.
- **CI (GitHub Actions)**:
  - Lint + unit tests (protocol parsing, flow control, probe-compensation math) on every push.
  - `arm64` build/artifact step (native ARM64 runner if available, else QEMU-emulated container) producing either the PyInstaller binary or a tagged release package.
  - Artifact/release published on tag.
- **Runtime dependencies on the Pi**: Qt runtime libs (`libgl1`, `libegl1`, etc.), pyserial, paho-mqtt — pinned in `requirements.txt`.

## 9. Key Risk Areas

| Area | Risk | Mitigation |
|---|---|---|
| Serial streaming | Buffer overflow/starvation stalls or corrupts jobs | Character-counting flow control, tested against real GRBL buffer size |
| Jogging | Queued G0/G1 jogs are not cancelable | Use GRBL `$J=` jog mode with jog-cancel real-time command |
| Alarm recovery | Limit-switch hits requiring app restart | Explicit Alarm state in `JobManager` with in-UI unlock flow |
| Probe accuracy | Overshoot at fast feedrate skews results | Two-stage fast-probe/slow-probe sequence |
| Packaging on ARM | Qt/OpenGL packaging breaks on Pi | Test artifacts on real Pi hardware in CI or pre-release checklist; prefer systemd deploy over frozen binary |

## 10. Directory Structure

```
app/
├── core/
│   ├── serial_transport.py
│   ├── grbl_adapter.py
│   ├── gcode_streamer.py
│   ├── job_manager.py
│   ├── probe.py
│   └── state.py
├── ha/
│   └── mqtt_bridge.py
├── ui/
│   ├── main_window.py
│   ├── jog_panel.py
│   ├── gcode_view.py
│   ├── toolpath_view.py
│   └── probe_wizard.py
├── main.py
└── config.yaml
```
