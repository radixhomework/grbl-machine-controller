"""Job-level state machine: Idle -> Running -> Paused -> (Alarm|Error|Complete)."""

from __future__ import annotations

import threading
from enum import Enum
from typing import Callable, List, Optional

from .gcode_streamer import GCodeStreamer
from .grbl_adapter import GRBLAdapter
from .state import MachineState


class JobState(Enum):
    IDLE = "Idle"
    RUNNING = "Running"
    PAUSED = "Paused"
    ALARM = "Alarm"
    ERROR = "Error"
    COMPLETE = "Complete"


class JobManager:
    def __init__(self, adapter: GRBLAdapter, state: MachineState,
                 on_log: Optional[Callable[[str], None]] = None):
        self.adapter = adapter
        self.state = state
        self.on_log = on_log or (lambda s: None)
        # delegate dynamically so a late on_log assignment (main window) is honored
        self.streamer = GCodeStreamer(adapter.transport, on_log=lambda s: self.on_log(s))
        adapter.ack_handler = self.streamer.on_line
        adapter.on_alarm.append(self._on_alarm)

        self.job_state = JobState.IDLE
        self.on_state: List[Callable[[JobState], None]] = []
        self._file = ""
        self._total_lines = 0

    def _set_state(self, s: JobState) -> None:
        self.job_state = s
        self.state.update(
            job_running=s == JobState.RUNNING,
            job_paused=s == JobState.PAUSED,
        )
        for cb in list(self.on_state):
            try:
                cb(s)
            except Exception:
                pass

    def load_file(self, path: str) -> int:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        clean = [l.strip() for l in lines
                 if l.strip() and not l.strip().startswith(("$", "%"))]
        self._file = path
        self._total_lines = len(clean)
        self.state.update(job_file=path, job_progress=0.0)
        return len(clean)

    def start(self) -> bool:
        if self.job_state not in (JobState.IDLE, JobState.COMPLETE, JobState.ERROR):
            return False
        if not self._file:
            return False
        with open(self._file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        self._set_state(JobState.RUNNING)
        self.adapter.send("G21")   # mm
        self.adapter.send("G90")   # absolute
        self.streamer.start(
            lines,
            on_progress=self._on_progress,
            on_done=self._on_done,
        )
        return True

    def pause(self) -> None:
        if self.job_state == JobState.RUNNING:
            self.adapter.hold()
            self.streamer.pause()
            self._set_state(JobState.PAUSED)

    def resume(self) -> None:
        if self.job_state == JobState.PAUSED:
            self.adapter.resume()
            self.streamer.resume()
            self._set_state(JobState.RUNNING)

    def stop(self) -> None:
        if self.job_state in (JobState.IDLE,):
            return
        self.streamer.abort()
        # issue feed-hold + soft reset to flush GRBL's planner buffer
        self.adapter.hold()
        self.adapter.reset()
        self._set_state(JobState.IDLE)
        self.state.update(job_progress=0.0)

    def _on_progress(self, frac: float) -> None:
        self.state.update(job_progress=frac)

    def _on_done(self, ok: bool, msg: str) -> None:
        if ok:
            self.on_log("Job complete")
            self._set_state(JobState.COMPLETE)
        else:
            self.on_log(f"Job failed: {msg}")
            self.state.update(last_error=None)
            self._set_state(JobState.ERROR)

    def _on_alarm(self, code: int) -> None:
        self.on_log(f"ALARM {code} — job halted")
        self.streamer.abort()
        self._set_state(JobState.ALARM)

    def unlock(self) -> bool:
        """Clear an alarm and return to Idle ($X)."""
        result = self.adapter.unlock()
        if result.ok:
            self._set_state(JobState.IDLE)
            self.state.update(alarm_code=None)
        return result.ok
