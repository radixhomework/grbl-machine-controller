# Probing & tool compensation

## Why compensation is needed

GRBL's `G38.2` probe reports the position of the **tool center** at the
moment of contact. The true workpiece edge is one tool radius away from that
point, on the side you approached from. All edge probing therefore
compensates:

```
true_edge = probed_position − tool_radius × approach_sign
```

where `approach_sign` is +1 or −1 depending on the approach direction
(X- probing means the tool moves in the −X direction, sign = −1).

The tool diameter comes from the tool table (Preferences → Tool table),
selected in the Probe panel's **Tool** dropdown. A diameter of 0 disables
compensation.

## The probe routine (single edge)

Each **Zero X- / Y- / Z-** button runs this sequence:

1. **Fast probe** — `G38.2` toward the surface at the fast feed (default
   300 mm/min) until contact.
2. **Retract** — pull away from the surface (default 2 mm) at rapid.
3. **Slow probe** — touch off again at the slow feed (default 30 mm/min).
   The slow pass removes the overshoot from the fast pass.
4. **Compensate** — compute the true edge (see above). For Z, the
   **Z probe size** preference is used instead: the contact point is treated
   as being that height above the true zero (e.g. the thickness of a touch
   plate; 0 = the probed surface is Z0). For X and Y, the **X / Y probe
   size** preferences apply: after compensation, the probed edge is set to
   read that value in the WCS. With the default 0 the edge itself becomes
   the zero; e.g. an X probe size of 5 places the work origin 5 mm into
   the material from the probed face (the face then reads X 5.000).
5. **Apply** — `G10 L20 P<wcs> <axis><true position>` so the work
   coordinate system reads the compensated value at the contact point.
6. **Pull off** — retract so the tool clears the surface.

Failure paths: no contact produces an error (GRBL alarm 8.1 style); the
panel shows the failure message and no offset is applied. **Cancel**
feed-holds and aborts mid-sequence.

## Corner finding

**Corner X-/Y-** runs the single-edge routine on two perpendicular faces in
sequence — first the X− edge, then the Y− edge — zeroing both axes. After it
finishes, the physical corner of the workpiece is the work origin (X0 Y0),
with tool compensation applied on both axes. You only need to jog the tool
near each face; the routine handles approach, retract, and offset.

This is the fastest way to set up a part clamped against two machined
reference edges: one button instead of two separate edge probes.

## Configuration

Probe speeds and distances live in Preferences (or `config.yaml`):

| Key | Meaning | Default |
|---|---|---|
| `fast_feed` | first touch speed (mm/min) | 300 |
| `slow_feed` | accurate touch speed (mm/min) | 30 |
| `retract` | pull-off between passes (mm) | 2.0 |
| `target` | search distance toward the surface (mm) | 20 |
| `z_probe_size` | height the Z contact represents above zero (mm) | 0 |
