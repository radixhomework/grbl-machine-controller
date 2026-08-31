"""GRBLAdapter — generic command surface <-> GRBL dialect.

- Real-time single-byte commands bypass all queueing.
- Buffered commands go through a small ordered queue; `send()` returns a
  per-command result object whose `wait()` blocks for ok/error.
- Status polling (~150ms) parses `<...>` reports into MachineState.
"""

from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .state import MachineState, Overrides, Position

RT_STATUS = b"?"
RT_FEED_HOLD = b"!"
RT_CYCLE_START = b"~"
RT_SOFT_RESET = b"\x18"
RT_JOG_CANCEL = b"\x85"

_STATUS_RE = re.compile(r"<([^|>]+)(.*)>")
_KV_RE = re.compile(r"(\w+):([^|>]+)")


@dataclass
class CommandResult:
    done: threading.Event = field(default_factory=threading.Event)
    ok: bool = False
    error_code: Optional[int] = None
    response: str = ""

    def wait(self, timeout: float = 30.0) -> "CommandResult":
        self.done.wait(timeout)
        return self


class GRBLAdapter:
    """Owns the transport; parses GRBL responses; exposes the command API."""

    def __init__(self, transport, state: MachineState, poll_interval: float = 0.15,
                 on_log: Optional[Callable[[str], None]] = None):
        self.transport = transport
        self.state = state
        self.poll_interval = poll_interval
        self.on_log = on_log or (lambda s: None)
        self.on_alarm: List[Callable[[int], None]] = []
        self.on_wco: List[Callable[[Position], None]] = []
        # Optional hook (the G-code streamer) that gets first chance at ok/error
        self.ack_handler: Optional[Callable[[str], bool]] = None

        self._rx_queue: "queue.Queue[str]" = queue.Queue()
        self._cmd_queue: "queue.Queue[tuple]" = queue.Queue()
        self._probe_result: Optional[Position] = None
        self._probe_event = threading.Event()
        self._last_wco: Optional[Position] = None
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._rx_thread: Optional[threading.Thread] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._cmd_thread: Optional[threading.Thread] = None

    # ---- lifecycle -------------------------------------------------------
    def connect(self) -> None:
        self._stop.clear()
        self.transport.open()
        self.state.update(connected=True)
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True, name="grbl-rx")
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name="grbl-poll")
        self._cmd_thread = threading.Thread(target=self._cmd_loop, daemon=True, name="grbl-cmd")
        for t in (self._rx_thread, self._poll_thread, self._cmd_thread):
            t.start()
        # wake GRBL (it resets on port open) and force a status report
        self.transport.write(RT_SOFT_RESET)
        time.sleep(2.0)  # GRBL boot delay
        self.transport.write(RT_STATUS)

    def close(self) -> None:
        self._stop.set()
        time.sleep(0.05)
        try:
            self.transport.close()
        finally:
            self.state.update(connected=False, grbl_state="Offline")

    # ---- low-level -------------------------------------------------------
    def realtime(self, data: bytes) -> None:
        self.transport.write(data)

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                line = self._rx_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            self._parse_line(line)

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self.transport.write(RT_STATUS)
            self._stop.wait(self.poll_interval)

    def _cmd_loop(self) -> None:
        """Serialized sender for one-off buffered commands (settings, G10...)."""
        while not self._stop.is_set():
            try:
                line, result = self._cmd_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            self.on_log(f">> {line}")
            self._awaiting: List[CommandResult] = getattr(self, "_awaiting", [])
            self._awaiting.append(result)
            self.transport.write_line(line)

    def send(self, line: str, timeout: float = 30.0) -> CommandResult:
        """Send a buffered command and wait for its ok/error."""
        result = CommandResult()
        self._cmd_queue.put((line, result))
        result.wait(timeout)
        if not result.done.is_set():
            result.ok = False
            result.error_code = -1  # timeout
        return result

    # ---- parsing ---------------------------------------------------------
    def _parse_line(self, raw: str) -> None:
        line = raw.strip()
        if not line:
            return
        self.on_log(f"<< {line}")

        if line.startswith("<") and line.endswith(">"):
            self._parse_status(line)
            return
        if line.startswith("ALARM:"):
            code = int(line.split(":", 1)[1])
            self.state.update(grbl_state="Alarm", alarm_code=code, job_running=False)
            for cb in list(self.on_alarm):
                try:
                    cb(code)
                except Exception:
                    pass
            return
        if line == "ok":
            if not (self.ack_handler and self.ack_handler(line)):
                self._resolve_pending(True, None, line)
            return
        m = re.match(r"error:(\d+)", line)
        if m:
            code = int(m.group(1))
            self.state.update(last_error=code)
            if not (self.ack_handler and self.ack_handler(line)):
                self._resolve_pending(False, code, line)
            return
        if line.startswith("[PRB:"):
            self._parse_probe(line)
            return
        if line.startswith("[MSG:") or line.startswith("Grbl") or line.startswith("["):
            return  # informational
        # unknown async line — resolve oldest pending anyway to avoid deadlock
        self._resolve_pending(True, None, line)

    def _resolve_pending(self, ok: bool, code, response: str) -> None:
        # single-flight: one buffered command in flight from _cmd_loop
        pending: List[CommandResult] = getattr(self, "_awaiting", [])
        if pending:
            result = pending.pop(0)
            result.ok = ok
            result.error_code = code
            result.response = response
            result.done.set()

    def _parse_status(self, line: str) -> None:
        body = line[1:-1]
        parts = body.split("|")
        grbl_state = parts[0]
        changes = {"connected": True, "grbl_state": grbl_state}
        for part in parts[1:]:
            m = _KV_RE.match(part)
            if not m:
                continue
            key, val = m.group(1), m.group(2)
            if key == "MPos":
                x, y, z = (float(v) for v in val.split(","))
                changes["mpos"] = Position(x, y, z)
            elif key == "WPos":
                x, y, z = (float(v) for v in val.split(","))
                changes["wpos"] = Position(x, y, z)
            elif key == "WCO":
                x, y, z = (float(v) for v in val.split(","))
                self._last_wco = Position(x, y, z)
            elif key == "FS":
                f, s = val.split(",")
                changes["feed_rate"] = float(f)
                changes["spindle_rpm"] = float(s)
                changes["spindle_on"] = float(s) > 0
            elif key == "Ov":
                f, r, s = (int(v) for v in val.split(","))
                changes["overrides"] = Overrides(f, r, s)
            elif key == "Pn":
                changes["pin_states"] = tuple(val.split(","))
        if grbl_state != "Alarm":
            changes["alarm_code"] = None
        self.state.update(**changes)

    def _parse_probe(self, line: str) -> None:
        # [PRB:x,y,z:1] — success flag is 1 on contact
        body = line[5:-1]
        coords, _, flag = body.partition(":")
        if flag.strip() == "1":
            x, y, z = (float(v) for v in coords.split(","))
            self._probe_result = Position(x, y, z)
        else:
            self._probe_result = None
        self._probe_event.set()

    # ---- command API (§5 of ARCHITECTURE.md) ------------------------------
    def jog(self, axis: str, distance: float, feedrate: float) -> CommandResult:
        return self.send(f"$J=G91{axis}{distance:+.3f}F{feedrate:.0f}")

    def jog_cancel(self) -> None:
        self.realtime(RT_JOG_CANCEL)

    def move_absolute(self, x=None, y=None, z=None, feedrate=1000) -> CommandResult:
        parts = ["G90"]
        for ax, v in (("X", x), ("Y", y), ("Z", z)):
            if v is not None:
                parts.append(f"{ax}{v:.3f}")
        parts.append(f"F{feedrate:.0f}")
        return self.send(" ".join(parts))

    def home_all(self) -> CommandResult:
        return self.send("$H")

    def reset_machine_pos(self) -> CommandResult:
        """Zero the machine coordinate display (G10 L2 P0 X0 Y0 Z0)."""
        return self.send("G10L2P0X0Y0Z0")

    def set_spindle_speed(self, rpm: float) -> CommandResult:
        return self.send(f"S{rpm:.0f}")

    def spindle_on(self, clockwise=True) -> CommandResult:
        return self.send("M3" if clockwise else "M4")

    def spindle_off(self) -> CommandResult:
        return self.send("M5")

    def start_probe(self, axis: str, distance: float, feedrate: float) -> Position:
        """Run G38.2 and return contact position, or raise on failure."""
        self._probe_event.clear()
        self._probe_result = None
        self.send(f"G38.2{axis}{distance:+.3f}F{feedrate:.0f}", timeout=120)
        self._probe_event.wait(timeout=5)
        if self._probe_result is None:
            raise RuntimeError("Probe failed: no contact")
        return self._probe_result

    def set_work_offset(self, wcs: str, x=None, y=None, z=None) -> CommandResult:
        p = int(wcs[1:]) if wcs.startswith("G") and wcs[1:].isdigit() else 1
        parts = [f"G10L20P{p}"]
        for ax, v in (("X", x), ("Y", y), ("Z", z)):
            if v is not None:
                parts.append(f"{ax}{v:.3f}")
        return self.send(" ".join(parts))

    def set_feed_override(self, pct: int) -> None:
        self._send_override(0x91, 0x90, 0x92, pct, step=1, lo=10, hi=200)

    def set_spindle_override(self, pct: int) -> None:
        self._send_override(0x9A, 0x99, 0x9B, pct, step=1, lo=10, hi=200)

    def set_rapid_override(self, pct: int) -> None:
        target = {25: [0x95], 50: [0x94], 100: [0x93]}[pct]
        for b in target:
            self.realtime(bytes([b]))

    def _send_override(self, up, down, reset, pct, step, lo, hi) -> None:
        pct = max(lo, min(hi, pct))
        current = self.state.snapshot().overrides.feed
        n = abs(pct - current)
        cmd = up if pct > current else down
        for _ in range(n):
            self.realtime(bytes([cmd]))

    def hold(self) -> None:
        self.realtime(RT_FEED_HOLD)

    def resume(self) -> None:
        self.realtime(RT_CYCLE_START)

    def reset(self) -> None:
        self.realtime(RT_SOFT_RESET)

    def unlock(self) -> CommandResult:
        return self.send("$X")
