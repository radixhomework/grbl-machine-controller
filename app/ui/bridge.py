"""Qt <-> core bridge: forwards MachineState updates onto the Qt event loop."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class StateBridge(QObject):
    stateChanged = Signal(object, object)   # new snapshot, old snapshot
    logLine = Signal(str)

    def __init__(self, state):
        super().__init__()
        self.state = state
        state.subscribe(self._on_state)

    def _on_state(self, new, old):
        self.stateChanged.emit(new, old)
