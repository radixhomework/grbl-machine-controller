"""Character-counting flow control: no overflow, no starvation, ordered acks."""

import threading
import time

from app.core.gcode_streamer import GCodeStreamer


class RecordingTransport:
    """Fake transport that enforces the 128-byte RX buffer contract."""

    RX = 128

    def __init__(self, delay=0.0):
        self.sent = []
        self.unacked_bytes = 0
        self.lock = threading.Lock()
        self.delay = delay
        self.on_line = None  # set by test: ack pump

    def write_line(self, line):
        data = line + "\n"
        with self.lock:
            assert self.unacked_bytes + len(data) <= self.RX, "RX buffer overflow!"
            self.unacked_bytes += len(data)
            self.sent.append(line)
        if self.delay:
            time.sleep(self.delay)

    def ack_one(self):
        """Ack the oldest sent line, like GRBL does (FIFO)."""
        with self.lock:
            line = self.sent[self._acked]
            self.unacked_bytes -= len(line) + 1
            self._acked += 1
            n = self._acked
        self.streamer.on_line("ok")

    _acked = 0

    def ack_all(self, streamer):
        self.streamer = streamer
        while self._acked < len(self.sent):
            self.ack_one()


def test_respects_buffer_limit_with_slow_acks():
    t = RecordingTransport()
    s = GCodeStreamer(t)
    t.streamer = s
    lines = [f"G1 X{i} Y{i}" for i in range(50)]
    done = threading.Event()
    s.start(lines, on_done=lambda ok, msg: done.set())
    # let the sender fill the window while we trickle acks
    for _ in range(50):
        t.ack_all(s)
        time.sleep(0.005)
    assert done.wait(5)
    assert t._acked == 50
    assert s.in_flight_bytes == 0


def test_all_lines_sent_in_order():
    t = RecordingTransport()
    s = GCodeStreamer(t)
    t.streamer = s
    lines = [f"G1 X{i}" for i in range(30)]
    done = threading.Event()
    s.start(lines, on_done=lambda ok, msg: done.set())
    deadline = time.time() + 5
    while t._acked < 30 and time.time() < deadline:
        t.ack_all(s)
        time.sleep(0.002)
    assert done.is_set()
    assert t.sent == lines  # order preserved


def test_error_aborts_stream():
    t = RecordingTransport()
    s = GCodeStreamer(t)
    t.streamer = s
    lines = [f"G1 X{i}" for i in range(10)]
    result = {}
    done = threading.Event()

    def on_done(ok, msg):
        result["ok"] = ok
        result["msg"] = msg
        done.set()

    s.start(lines, on_done=on_done)
    # ack line 0 as error
    deadline = time.time() + 5
    while not t.sent and time.time() < deadline:
        time.sleep(0.005)
    s.on_line("error:33")
    assert done.wait(5)
    assert result["ok"] is False
    assert "error:33" in result["msg"]


def test_pause_stops_sending():
    t = RecordingTransport()
    s = GCodeStreamer(t)
    t.streamer = s
    lines = [f"G1 X{i}" for i in range(20)]
    s.start(lines)
    time.sleep(0.05)
    s.pause()
    time.sleep(0.05)
    n_at_pause = len(t.sent)
    time.sleep(0.1)
    assert len(t.sent) == n_at_pause  # nothing more while paused and window stays full
    s.resume()
    deadline = time.time() + 5
    while t._acked < 20 and time.time() < deadline:
        t.ack_all(s)
        time.sleep(0.002)
    assert t._acked == 20
