# Configuration reference

Configuration lives in `config.yaml` (path overridable with `--config`).
Everything except the serial port can also be edited in the app via
**File → Preferences**, which writes the file back.

```yaml
serial:
  port: /dev/ttyUSB0           # serial device; also --port on the command line
  baud: 115200                 # GRBL default
  status_poll_interval: 0.15   # seconds between '?' status polls

mqtt:
  enabled: false               # master switch for the Home Assistant bridge
  host: homeassistant.local    # MQTT broker host
  port: 1883
  username: ""                 # leave empty for anonymous
  password: ""
  base_topic: cnc              # state on cnc/state, commands on cnc/cmd/...
  discovery_prefix: homeassistant

tools:                         # tool table used by the probe panel
  1: { diameter: 6.0,   note: "6mm endmill" }
  2: { diameter: 3.175, note: "1/8\" endmill" }

probe:
  fast_feed: 300               # first touch (mm/min)
  slow_feed: 30                # accurate touch (mm/min)
  retract: 2.0                 # pull-off between passes (mm)
  target: -20.0                # search distance (sign = probing direction)
  x_probe_size: 0.0            # value the probed X edge reads in the WCS
  y_probe_size: 0.0            # value the probed Y edge reads in the WCS
  z_probe_size: 0.0            # height the Z contact represents above true
                               # zero, e.g. touch-plate thickness

defaults:
  jog_feed: 1000               # initial jog feed (mm/min)
  jog_distance: 1.0            # initial jog step (mm)
  spindle_rpm: 1000            # initial spindle speed
```

## Notes

- **Serial** changes require a restart, or **Machine → Reconnect**.
- **Tool diameters** are what the probe compensation uses; keep them current
  with the real tools.
- `z_probe_size` applies only to Z probing: after the touch-off, the work
  origin is placed that many millimeters below the contact point. With a
  10 mm touch plate, set it to `10.0` and the plate's top surface probes to
  work Z = 10.0, putting Z0 at the table/part underneath.
- `x_probe_size` / `y_probe_size` apply to X/Y edge probing: the probed
  face reads that value in the WCS, shifting the zero into the material
  (e.g. `5.0` makes the probed face read X 5.000).
- The file is rewritten by the Preferences dialog in normalized form
  (comments are lost on save).
