# Home Assistant integration

The app integrates with Home Assistant as a **plain MQTT client** using
HA's built-in MQTT discovery — no custom HA component is installed or
maintained. You need an MQTT broker (e.g. the Mosquitto broker add-on) that
Home Assistant is already configured to use.

## Setup

1. In the app: **File → Preferences → Home Assistant / MQTT**.
2. Enable it, enter the broker host/port and credentials, then OK.
3. Restart the app (MQTT connects at startup). Entities appear in HA
   automatically.

## Published entities

All state is published retained on `cnc/state` (with `base_topic: cnc`),
throttled to ~1 Hz.

| Entity | Type | Value |
|---|---|---|
| Machine status | sensor | GRBL state (Idle, Run, Hold, Alarm…) |
| X / Y / Z position | sensor (mm) | machine position |
| Spindle RPM | sensor (rpm) | reported spindle speed |
| Job progress | sensor (%) | streamed job completion |
| Job running | binary_sensor | a job is being streamed |
| Alarm active | binary_sensor | GRBL is in an alarm state |
| Home / Unlock / Pause / Resume / Stop | button | job & machine controls |
| Feed override | number (10–200 %) | feed override setpoint |
| Spindle override | number (10–200 %) | spindle override setpoint |

## Commands

Buttons and numbers publish to `cnc/cmd/<action>`:

```
cnc/cmd/home              "1"
cnc/cmd/unlock            "1"
cnc/cmd/pause             "1"
cnc/cmd/resume            "1"
cnc/cmd/stop              "1"
cnc/cmd/feed_override     "120"
cnc/cmd/spindle_override  "110"
```

This gives you dashboard cards, automations (e.g. "notify when alarm
active"), and voice control with zero HA-side configuration.
