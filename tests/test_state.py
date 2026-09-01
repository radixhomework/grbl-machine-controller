"""MachineState observable behavior."""

from app.core.state import MachineState, Position


def test_update_notifies_subscribers():
    state = MachineState()
    seen = []
    state.subscribe(lambda new, old: seen.append((new.mpos.x, old.mpos.x)))
    state.update(mpos=Position(x=1.0))
    assert seen == [(1.0, 0.0)]


def test_snapshot_is_isolated():
    state = MachineState()
    snap = state.snapshot()
    state.update(grbl_state="Run")
    assert snap.grbl_state == "Offline"
    assert state.snapshot().grbl_state == "Run"


def test_unsubscribe():
    state = MachineState()
    calls = []
    cb = lambda new, old: calls.append(1)
    state.subscribe(cb)
    state.unsubscribe(cb)
    state.update(grbl_state="Run")
    assert calls == []
