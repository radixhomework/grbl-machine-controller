"""G-code streaming with character-counting flow control (§4.3).

Keeps GRBL's 128-byte RX buffer full (no planner starvation) without ever
overflowing it: a line is only written when (in-flight bytes + line bytes)
fits within the buffer, and in-flight bytes are released as the matching
ok/error acknowledgments arrive in order (GRBL acks strictly FIFO).
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional

RX_BUFFER_SIZE = 128
SAFETY_MARGIN = 2  # headroom for real-time bytes that share the wire


class GCodeStreamer:
    def __init__(self, transport, on_log: Optional[Callable[[str], None]] = None):
        self.transport = transport
        self.on_log = on_log or (lambda s: None)
        self.rx_size = RX_BUFFER_SIZE
        self._in_flight = 0
        self._pending: List[tuple] = []  # (nbytes, line, ack_cb), FIFO
        self._lock = threading.Lock()
        self._wake = threading.Event()

        self._lines: List[str] = []
        self._next_index = 0
        self._acked_count = 0
        self._progress_cb: Optional[Callable[[float], None]] = None
        self._done_cb: Optional[Callable[[bool, str], None]] = None
        self._error = ""
        self._abort = False
        self._paused = False
        self._active = False

    # ---- ack path (called from the adapter's rx thread) --------------------
    def on_line(self, line: str) -> bool:
        """Return True if this line was an ack for a streamed line."""
        if not (line == "ok" or line.startswith("error:")):
            return False
        with self._lock:
            if not self._pending:
                return False  # ack for a one-off command, not the stream
            nbytes, sent_line, cb = self._pending.pop(0)
            self._in_flight = max(0, self._in_flight - nbytes)
        self._wake.set()
        cb(line)
        return True

    # ---- streaming ---------------------------------------------------------
    def start(self, lines: List[str],
              on_progress: Optional[Callable[[float], None]] = None,
              on_done: Optional[Callable[[bool, str], None]] = None) -> None:
        clean = [l.strip() for l in lines
                 if l.strip() and not l.strip().startswith(("$", "%"))]
        with self._lock:
            self._lines = clean
            self._next_index = 0
            self._acked_count = 0
            self._in_flight = 0
            self._pending = []
            self._error = ""
            self._abort = False
            self._paused = False
            self._active = bool(clean)
            self._progress_cb = on_progress
            self._done_cb = on_done
        if not clean:
            self._finish(True, "")
            return
        threading.Thread(target=self._run, daemon=True, name="gcode-stream").start()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False
        self._wake.set()

    def abort(self) -> None:
        self._abort = True
        self._wake.set()

    @property
    def in_flight_bytes(self) -> int:
        return self._in_flight

    @property
    def is_active(self) -> bool:
        return self._active

    # ---- internals ---------------------------------------------------------
    def _run(self) -> None:
        total = len(self._lines)
        while True:
            if self._abort:
                self._finish(False, self._error or "aborted")
                return
            if self._acked_count >= total:
                self._finish(True, "")
                return

            sent = False
            with self._lock:
                if self._paused or self._next_index >= total:
                    pass
                else:
                    line = self._lines[self._next_index]
                    nbytes = len(line.encode("ascii", "replace")) + 1
                    if self._in_flight + nbytes <= self.rx_size - SAFETY_MARGIN:
                        self.transport.write_line(line)
                        self._in_flight += nbytes
                        index = self._next_index
                        self._next_index += 1
                        self._pending.append((nbytes, line, self._make_ack(index, total)))
                        sent = True
            if not sent:
                self._wake.wait(timeout=0.05)
                self._wake.clear()

    def _make_ack(self, index: int, total: int) -> Callable:
        def ack(line: str):
            self._acked_count += 1
            self.on_log(f">> {self._lines[index]}  ⇒  {line}")
            if line.startswith("error:"):
                self._error = f"GRBL {line} at line {index + 1}: {self._lines[index]!r}"
                self._abort = True
            elif self._progress_cb:
                self._progress_cb(self._acked_count / total)
            self._wake.set()
        return ack

    def _finish(self, ok: bool, msg: str) -> None:
        with self._lock:
            done_cb, progress_cb, total = self._done_cb, self._progress_cb, len(self._lines)
            self._done_cb = None
            self._active = False
        if ok and progress_cb and total:
            progress_cb(1.0)
        if done_cb:
            done_cb(ok, msg or self._error)
