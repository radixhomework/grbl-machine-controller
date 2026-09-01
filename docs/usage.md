# Usage

## Running

```bash
pip install -r requirements.txt

python -m app.main --fake            # built-in GRBL simulator (no hardware)
python -m app.main --port /dev/ttyUSB0
python -m app.main --port COM3       # Windows serial port
python -m app.main --config my.yaml  # alternate config file
python -m app.main --headless        # core + MQTT only, no window
```

The window title bar shows the connection state; the bottom status bar shows
machine position, overrides and job progress at a glance.

## Main window layout

```
┌──────────────────────────────────────┬───────────┐
│                                      │ Coordinates│
│              3D preview              │  Probe     │
│   (drag to orbit, wheel to zoom,     │  Jog       │
│    view presets in the top-right)    │  Spindle   │
│                                      │  Job       │
├──────────────────────────────────────┴───────────┤
│        Command log: # | Command | State | Response│
└──────────────────────────────────────────────────┘
```

All dividers are draggable — grab the thin gray line between areas
(it highlights blue on hover).

## Coordinates panel

Three rows:

- **Work** — X/Y/Z in the active work coordinate system. This is what the
  G-code coordinates refer to; probe zeros and manual zeros apply here.
- **Machine** — X/Y/Z relative to the machine's home/reference. **Reset**
  zeroes the machine coordinate display (`G10 L2 P0`).
- **Status** — the GRBL state (Idle, Run, Hold, Jog, Alarm…) and, when
  something goes wrong, the alarm or error code.

## Probe panel

Select the **tool** (from the tool table in Preferences) and the **WCS**
(e.g. G54), then:

- **Zero X- / Y- / Z-** — probe the corresponding edge or surface. The tool
  touches off twice (fast, then slow) and the work zero is set at the true
  surface, compensating for the tool radius. See
  [Probing](probing.md) for the math. For Z, the *Z probe size* preference
  is honored (e.g. touch-plate thickness).
- **Set 0: X = 0 / Y = 0 / Z = 0** — manual zeroing. Jog the tool where you
  want it and click; the current position becomes zero for that axis.
  No probing, no compensation.
- **Corner X-/Y-** — probes two perpendicular edges in one routine and sets
  both zeros, making the workpiece corner the origin (X0 Y0). Useful when a
  part is clamped against two reference edges.
- **Cancel** — abort a running probe (feed hold).

## Jog panel

Set a **step** (type a value or click 0.1 / 1 / 10) and **feed**, then use
the direction pad. Jogs use GRBL's `$J=` mode, so **Stop** cancels a move
instantly mid-motion. **Home** runs the homing cycle (`$H`).

## Spindle panel

- **rpm** — target speed; changing it while the spindle runs updates live.
- **CW / CCW** — rotation direction, applied at the next start.
- **ON** — starts/stops the spindle (`M3`/`M4`/`M5`).
- The readout under the button shows the *actual* speed GRBL reports.

## Job panel

1. Load G-code via **File → Open G-code** (Ctrl+O). The file appears in the
   3D preview at the same time.
2. **Start** streams the job with proper flow control (GRBL's buffer is kept
   full but never overflows). **Pause** feed-holds, **Resume** continues,
   **Stop** aborts, **Unlock** clears an alarm (`$X`).
3. The **MDI** field sends a single line straight to GRBL (e.g. `G0 X10 Y0`).

If a job triggers an alarm, the state turns red, the job halts, and
**Unlock** becomes available.

## Menus

- **File** — open G-code, Preferences (serial, defaults, probe, MQTT, tool
  table), Exit
- **Machine** — home, unlock, feed hold, resume, soft reset, reconnect
- **Help** — About

## Command log

The bottom panel is a table with one row per command:

| Column | Contents |
|---|---|
| **#** | Sequential command number (shared counter across MDI, jobs, probing) |
| **Command** | The line sent to GRBL |
| **State** | The machine state when the command was sent (Idle, Run…) |
| **Response** | What GRBL answered: `ok`, `error:N`, `[PRB:…]`, `ALARM:N`… |

Responses in red are errors, alarms, or timeouts. Machine-initiated messages
and progress info (e.g. "Probe: contact at …", "Job complete") appear as
unnumbered rows. Status report spam is not logged — it feeds the DRO and
status bar instead.

## 3D preview

- **Left-drag** orbits, **wheel** zooms.
- The **dropdown in the top-right** snaps to a preset view (Iso, Top, Front,
  Back, Left, Right).
- Blue lines are cutting moves, thin gray lines are rapids; arcs are
  approximated with chords.
- While a job runs, a **red marker** with a dashed drop-line shows the live
  tool position on the path.
