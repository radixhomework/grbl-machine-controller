"""XY/Z probing with tool-diameter compensation (§6 of ARCHITECTURE.md).

Runs as an explicit step sequence on a worker thread:
fast probe -> retract -> slow probe -> compensate for tool radius ->
apply work offset via G10 L20.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

from .grbl_adapter import GRBLAdapter

APPROACH_SIGN = {"X+": 1, "X-": -1, "Y+": 1, "Y-": -1, "Z+": 1, "Z-": -1}
AXIS_OF = {"X+": "X", "X-": "X", "Y+": "Y", "Y-": "Y", "Z+": "Z", "Z-": "Z"}


@dataclass
class ProbeConfig:
    direction: str            # one of APPROACH_SIGN keys, approach *toward* the surface
    tool_diameter: float      # mm; 0 disables compensation
    fast_feed: float = 300.0
    slow_feed: float = 30.0
    retract: float = 2.0
    travel: float = -20.0     # search distance sign follows the direction
    wcs: str = "G54"
    z_ref_height: float = 0.0  # mm: for Z probes, the height the contact point
                               # represents above the true zero (e.g. touch-plate thickness)


@dataclass
class ProbeResult:
    ok: bool
    raw_position = None       # tool center at slow-probe contact
    compensated = None        # true edge position
    message: str = ""


class ProbeController:
    def __init__(self, adapter: GRBLAdapter, on_log: Optional[Callable[[str], None]] = None):
        self.adapter = adapter
        self.on_log = on_log or (lambda s: None)
        self.cancelled = threading.Event()
        self.busy = False

    def cancel(self) -> None:
        self.cancelled.set()
        self.adapter.realtime(b"!")   # feed hold stops an in-motion probe

    # ---- compensation math (pure, unit-tested) -----------------------------
    @staticmethod
    def compensate(raw: float, tool_diameter: float, direction: str) -> float:
        """True surface position from probed tool-center position.

        The tool center sits one radius *inside* the workpiece from the true
        edge, on the approach side, so subtract radius * approach_sign.
        """
        radius = tool_diameter / 2.0
        sign = APPROACH_SIGN[direction]
        return raw - radius * sign

    # ---- full routine -------------------------------------------------------
    def run_edge(self, cfg: ProbeConfig) -> ProbeResult:
        """Probe one edge and set the WCS origin at the true edge (zeroed)."""
        self.busy = True
        self.cancelled.clear()
        result = ProbeResult(ok=False, message="")
        axis = AXIS_OF[cfg.direction]
        sign = APPROACH_SIGN[cfg.direction]
        try:
            self.on_log(f"Probe: fast pass {cfg.direction} @ {cfg.fast_feed}")
            raw_pos = self._probe_once(axis, sign, cfg)
            raw = raw_pos[0]           # axis coordinate as float
            result.raw_position = raw_pos[1]

            if axis == "Z":
                # contact point sits z_ref_height above the true zero
                true_val = cfg.z_ref_height
            else:
                true_val = self.compensate(raw, cfg.tool_diameter, cfg.direction)
            result.compensated = true_val

            self.on_log(f"Probe: contact at {raw:.3f}, edge at {true_val:.3f} "
                        f"(r={cfg.tool_diameter / 2:.3f})")
            r = self.adapter.set_work_offset(cfg.wcs, **{axis.lower(): true_val})
            if not r.ok:
                result.message = f"G10 failed: {r.response}"
                return result
            # pull off the surface so the tool is clear afterwards
            self.adapter.move_absolute(**{axis.lower(): raw + sign * cfg.retract}, feedrate=600)
            result.ok = True
            return result
        except RuntimeError as e:
            result.message = str(e)
            return result
        finally:
            self.busy = False

    def run_corner(self, cfg_x: ProbeConfig, cfg_y: ProbeConfig,
                   z_probe: Optional[ProbeConfig] = None) -> ProbeResult:
        """Two perpendicular edges (+ optional Z touch) to zero X, Y (,Z)."""
        for cfg in (cfg_x, cfg_y):
            r = self.run_edge(cfg)
            if not r.ok:
                return r
        if z_probe is not None:
            return self.run_edge(z_probe)
        return ProbeResult(ok=True, message="Corner set")

    def _probe_once(self, axis: str, sign: int, cfg: ProbeConfig):
        """Fast probe, retract, slow probe. Returns (axis_value, Position)."""
        travel = abs(cfg.travel) * (-sign)  # travel direction is opposite the approach sign
        # fast pass
        raw = self.adapter.start_probe(axis, travel, cfg.fast_feed)
        self._check_cancel()
        raw_val = getattr(raw, axis.lower())
        # retract away from the surface
        back = raw_val + sign * cfg.retract
        r = self.adapter.move_absolute(**{axis.lower(): back}, feedrate=600)
        if not r.ok:
            raise RuntimeError("Retract failed")
        # slow pass
        raw_slow = self.adapter.start_probe(axis, travel, cfg.slow_feed)
        self._check_cancel()
        return getattr(raw_slow, axis.lower()), raw_slow

    def _check_cancel(self) -> None:
        if self.cancelled.is_set():
            raise RuntimeError("Probe cancelled")
