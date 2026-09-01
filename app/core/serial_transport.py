"""Raw serial transport (no GRBL logic) plus an in-process fake for testing.

Real-time single-byte commands and normal lines all go through write();
the transport guarantees they reach the wire in order. A dedicated read
thread pushes complete lines (\\r\\n terminated) to on_line callbacks.
"""

from __future__ import annotations

import queue
import threading
from typing import Callable, List, Optional

try:
    import serial  # pyserial
except ImportError:  # allows UI-only / test usage without pyserial
    serial = None


class LineReader:
    """Shared byte-stream -> line splitting used by both transports."""

    def __init__(self, on_line: Callable[[str], None]):
        self.on_line = on_line
        self._buf = bytearray()

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)
        while True:
            idx = -1
            for i, b in enumerate(self._buf):
                if b in (0x0A, 0x0D):  # \n or \r
                    idx = i
                    break
            if idx < 0:
                # avoid unbounded growth on garbage
                if len(self._buf) > 4096:
                    self._buf.clear()
                break
            line = bytes(self._buf[:idx]).decode("ascii", errors="replace").strip()
            del self._buf[: idx + 1]
            if line:
                self.on_line(line)


class SerialTransport:
    """pyserial-backed transport with auto-reconnect."""

    def __init__(self, port: str, baud: int = 115200, on_line: Optional[Callable[[str], None]] = None,
                 on_disconnected: Optional[Callable[[], None]] = None):
        if serial is None:
            raise RuntimeError("pyserial is not installed")
        self.port = port
        self.baud = baud
        self.on_disconnected = on_disconnected
        self._reader = LineReader(on_line) if on_line else None
        self._ser = None
        self._rx_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()

    def open(self) -> None:
        self._stop.clear()
        self._ser = serial.Serial(self.port, self.baud, timeout=0.1)
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True, name="serial-rx")
        self._rx_thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._rx_thread:
            self._rx_thread.join(timeout=2)
        if self._ser and self._ser.is_open:
            self._ser.close()

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def write(self, data: bytes) -> None:
        with self._write_lock:
            try:
                self._ser.write(data)
                self._ser.flush()
            except Exception:
                self._handle_disconnect()

    def write_line(self, line: str) -> None:
        self.write(line.encode("ascii", errors="replace") + b"\n")

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._ser.read(256)
                if data and self._reader:
                    self._reader.feed(data)
            except Exception:
                self._handle_disconnect()
                return

    def _handle_disconnect(self) -> None:
        try:
            if self._ser:
                self._ser.close()
        except Exception:
            pass
        if self.on_disconnected:
            self.on_disconnected()


class FakeTransport:
    """In-memory transport that pairs with app.core.fake_grbl.FakeGRBL.

    `peer` is the FakeGRBL; anything written here is handed to it, and
    everything the fake emits is delivered to on_line.
    """

    def __init__(self, on_line: Optional[Callable[[str], None]] = None):
        self.on_line = on_line
        self.peer = None  # set by FakeGRBL
        self.is_open = False

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def write(self, data: bytes) -> None:
        if not self.is_open:
            return
        if self.peer:
            self.peer.receive_bytes(data)

    def write_line(self, line: str) -> None:
        self.write(line.encode("ascii") + b"\n")

    # called by FakeGRBL
    def _deliver(self, line: str) -> None:
        if self.on_line:
            self.on_line(line)
