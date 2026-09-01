"""Observable machine state — single source of truth for the whole app."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import Callable, List, Optional


@dataclass(frozen=True)
class Position:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass(frozen=True)
class Overrides:
    feed: int = 100      # percent
    rapid: int = 100
    spindle: int = 100


@dataclass
class MachineState:
    """Everything we know about "what is the machine doing right now".

    Mutated only through :meth:`update`, which notifies subscribers with the
    changed snapshot. Subscribers receive (new_state, old_state).
    """

    connected: bool = False
    grbl_state: str = "Offline"          # Idle/Run/Hold/Jog/Alarm/Door/Check/Home/Offline
    mpos: Position = field(default_factory=Position)
    wpos: Position = field(default_factory=Position)
    wcs: str = "G54"
    feed_rate: float = 0.0               # current rate, mm/min
    spindle_rpm: float = 0.0
    spindle_on: bool = False
    overrides: Overrides = field(default_factory=Overrides)
    pin_states: tuple = ()               # e.g. ("HOLD", "LimX")
    alarm_code: Optional[int] = None
    last_error: Optional[int] = None
    # Job-level info (owned by JobManager)
    job_running: bool = False
    job_paused: bool = False
    job_progress: float = 0.0            # 0..1
    job_file: str = ""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _subscribers: List[Callable] = field(default_factory=list, repr=False)

    def subscribe(self, callback: Callable[["MachineState", "MachineState"], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def update(self, **changes) -> "MachineState":
        """Return an updated snapshot, store it, and notify subscribers."""
        with self._lock:
            old = replace(self)
            new = replace(self, **changes)
            self.__dict__.update(new.__dict__)
            subscribers = list(self._subscribers)
        for cb in subscribers:
            try:
                cb(new, old)
            except Exception:
                import traceback
                traceback.print_exc()
        return new

    def snapshot(self) -> "MachineState":
        with self._lock:
            return replace(self)
