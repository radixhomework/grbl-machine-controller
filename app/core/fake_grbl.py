"""A minimal scripted GRBL simulator wired to FakeTransport.

Enough protocol fidelity for tests and offline UI development:
status reports, ok/error acks, $J= jog motion, G38.2 probe reports,
alarms, and version/banner on connect.
"""

from __future__ import annotations

import re
import threading
import time
from typing import List, Optional

from .serial_transport import FakeTransport

RX_BUFFER = 128

_REALTIME = {
    "?": "status",
    "!": "hold",
    "~": "resume",
    "\x18": "reset",
    "\x85": "jog_cancel",
}


class FakeGRBL:
    def __init__(self):
        self.transport = FakeTransport()
        self.transport.peer = self
        self.mpos = [0.0, 0.0, 0.0]
        self.wco = [0.0, 0.0, 0.0]
        self.state = "Idle"
        self.feed = 0.0
        self.spindle = 0.0
        self.ov = [100, 100, 100]
        self.pins: List[str] = []
        self.alarm = False
        self.rx_used = 0
        self._pending: List[str] = []
        self._lock = threading.Lock()
        self._motion_thread: Optional[threading.Thread] = None
        self._move_queue: List[tuple] = []   # serialized, like real GRBL's planner
        self._queue_cond = threading.Condition()
        self.probe_result: float = -10.0   # axis position where contact happens
        self.probe_contact = True
        self._intro_done = False

    # ---- transport side -------------------------------------------------
    def receive_bytes(self, data: bytes) -> None:
        # real-time bytes act immediately, even mid-line
        i = 0
        while i < len(data):
            ch = chr(data[i])
            if ch in _REALTIME:
                self._realtime(_REALTIME[ch])
                i += 1
                continue
            j = data.find(b"\n", i)
            if j < 0:
                chunk, i = data[i:].decode("ascii", "replace"), len(data)
            else:
                chunk, i = data[i:j].decode("ascii", "replace"), j + 1
            chunk = chunk.strip("\r ")
            if chunk:
                self._handle_line(chunk)

    def _emit(self, line: str) -> None:
        # small delay to exercise async parsing
        threading.Timer(0.001, self.transport._deliver, args=(line,)).start()

    # ---- protocol -------------------------------------------------------
    def _handle_line(self, line: str) -> None:
        if not self._intro_done:
            self._intro_done = True
            self._emit("Grbl 1.1h ['$' for help]")
        with self._lock:
            if self.alarm:
                self._emit("error:9")  # locked
                return
        if line.startswith("$J="):
            self._start_jog(line[3:])
            return
        if line.startswith("G38") or line.startswith("g38"):
            self._do_probe(line)
            return
        if line.startswith("$"):
            self._emit("ok")
            return
        upper = line.upper()
        if upper.startswith("G10"):
            m = re.search(r"P(\d+)", upper)
            if m:
                idx = int(m.group(1)) - 1
                if idx < 0:
                    # P0: machine-coordinate reset — makes MPos read zero
                    self.wco = [-v for v in self.mpos]
                elif "L20" in upper:
                    # L20: current position should read <value> in the WCS
                    for ax, val in re.findall(r"([XYZ])([-+]?\d+\.?\d*)", upper):
                        self.wco["XYZ".index(ax)] = self.mpos["XYZ".index(ax)] - float(val)
                else:
                    # L2: direct offset
                    for ax, val in re.findall(r"([XYZ])([-+]?\d+\.?\d*)", upper):
                        self.wco["XYZ".index(ax)] = float(val)
            self._emit("ok")
            return
        upper = line.upper()
        has_axis = re.search(r"([XYZ])([-+]?\d)", upper)
        if has_axis and not upper.startswith(("G10", "G28", "G30", "G92")):
            # axis words run in the current motion mode (default G0), like GRBL
            feed = self.feed or 500.0
            fm = re.search(r"F(\d+\.?\d*)", upper)
            if fm:
                feed = float(fm.group(1))
            self._start_move(self._targets(upper), feed)
            self._emit("ok")
            return
        if upper.split()[0] in ("G21", "G90", "G54") and not has_axis:
            self._emit("ok")   # pure modal line, no motion words
            return
        if upper.startswith("M3") or upper.startswith("M4") or upper.startswith("M5"):
            if upper.startswith("M5"):
                self.spindle = 0.0
            elif "S" in upper:   # M3 S1500 — set speed together with the mode
                self.spindle = float(upper.split("S")[1])
            # plain M3/M4 keeps the last S speed, like real GRBL
            self._emit("ok")
            return
        if upper.startswith("S"):
            self.spindle = float(upper[1:])
            self._emit("ok")
            return
        if upper.startswith("G0") or upper.startswith("G1"):
            self._start_move(self._targets(upper), (self.feed or 500.0) if upper.startswith("G1") else 2000.0)
            self._emit("ok")
            return
        if upper.startswith("F"):
            self.feed = float(upper[1:])
            self._emit("ok")
            return
        self._emit("ok")

    def _targets(self, line: str) -> List[float]:
        tgt = list(self.mpos)
        for ax, val in re.findall(r"([XYZ])([-+]?\d+\.?\d*)", line.upper()):
            tgt["XYZ".index(ax)] = float(val) + self.wco["XYZ".index(ax)]
        return tgt

    def _animate(self, target: List[float], feed_mm_min: float, kind: str, extra: Optional[dict] = None) -> None:
        """Queue a motion; a single worker executes moves in order (no overlap)."""
        with self._queue_cond:
            self._move_queue.append((target, feed_mm_min, kind, extra or {}))
            if self._motion_thread is None or not self._motion_thread.is_alive():
                self._motion_thread = threading.Thread(target=self._motion_worker, daemon=True)
                self._motion_thread.start()

    def _motion_worker(self) -> None:
        while True:
            with self._queue_cond:
                if not self._move_queue:
                    self._motion_thread = None
                    return
                target, feed, kind, extra = self._move_queue.pop(0)
            self._run_motion(target, feed, kind, extra)

    def _run_motion(self, target: List[float], feed_mm_min: float, kind: str, extra: dict) -> None:
        start = list(self.mpos)
        dist = max(abs(t - s) for t, s in zip(target, start)) or 0.001
        self.state = "Jog" if kind == "jog" else "Run"
        duration = max(0.02, min(2.0, dist / max(feed_mm_min, 1.0) * 60.0))
        t0 = time.time()
        hit = None
        while True:
            if self._jog_cancelled and kind == "jog":
                break
            frac = min(1.0, (time.time() - t0) / duration)
            for k in range(3):
                self.mpos[k] = start[k] + (target[k] - start[k]) * frac
            if kind == "probe" and self.probe_contact:
                axis = extra["axis"]
                sign = extra["sign"]
                pos = self.mpos[axis]
                if (sign < 0 and pos <= self.probe_result) or (sign > 0 and pos >= self.probe_result):
                    hit = frac
                    self.mpos[axis] = self.probe_result
                    break
            if frac >= 1.0:
                break
            time.sleep(0.01)
        if kind == "probe":
            if hit is not None:
                self._emit(f"[PRB:{self.mpos[0]:.3f},{self.mpos[1]:.3f},{self.mpos[2]:.3f}:{1}]")
                self._emit("ok")
            else:
                self._emit("error:8")
                self.alarm = True
                self.state = "Alarm"
        else:
            self.state = "Idle"

    def _start_jog(self, params: str) -> None:
        m = re.search(r"F(\d+\.?\d*)", params)
        feed = float(m.group(1)) if m else 1000.0
        tgt = list(self.mpos)
        for ax, val in re.findall(r"([XYZ])([-+]?\d+\.?\d*)", params.upper()):
            tgt["XYZ".index(ax)] += float(val)
        self._jog_cancelled = False
        self._emit("ok")   # real GRBL acks $J= immediately, motion runs async
        self._animate(tgt, feed, "jog")

    def _start_move(self, target: List[float], feed: float) -> None:
        self._animate(target, feed, "move")

    def _do_probe(self, line: str) -> None:
        m = re.search(r"([XYZ])([-+]?\d+\.?\d*)", line.upper())
        axis = "XYZ".index(m.group(1))
        delta = float(m.group(2))
        feed_m = re.search(r"F(\d+\.?\d*)", line)
        feed = float(feed_m.group(1)) if feed_m else 100.0
        target = list(self.mpos)
        target[axis] += delta
        self._animate(target, feed, "probe", extra={"axis": axis, "sign": -1 if delta < 0 else 1})

    def _realtime(self, cmd: str) -> None:
        if cmd == "status":
            self._emit(self._status_line())
        elif cmd == "hold":
            if self.state in ("Run", "Jog"):
                self.state = "Hold:0"
        elif cmd == "resume":
            if self.state.startswith("Hold"):
                self.state = "Run"
        elif cmd == "jog_cancel":
            self._jog_cancelled = True
        elif cmd == "reset":
            self.alarm = False
            self.state = "Idle"
            self._jog_cancelled = True
            self._emit("Grbl 1.1h ['$' for help]")

    def trigger_alarm(self, code: int = 9) -> None:
        self.alarm = True
        self.state = "Alarm"
        self._emit(f"ALARM:{code}")

    def _status_line(self) -> str:
        wco = ",".join(f"{v:.3f}" for v in self.wco)
        parts = [
            f"<{self.state.split(':')[0]}",
            f"MPos:{self.mpos[0]:.3f},{self.mpos[1]:.3f},{self.mpos[2]:.3f}",
            f"WPos:{self.mpos[0]-self.wco[0]:.3f},{self.mpos[1]-self.wco[1]:.3f},{self.mpos[2]-self.wco[2]:.3f}",
            f"WCO:{wco}",
        ]
        parts.append(f"FS:{self.feed:.0f},{self.spindle:.0f}")
        parts.append(f"Ov:{self.ov[0]},{self.ov[1]},{self.ov[2]}")
        if self.pins:
            parts.append("Pn:" + ",".join(self.pins))
        return "|".join(parts) + ">"
