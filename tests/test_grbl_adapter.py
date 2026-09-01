"""GRBL protocol parsing and command API against the FakeGRBL simulator."""

import time

import pytest

from app.core.fake_grbl import FakeGRBL
from app.core.grbl_adapter import GRBLAdapter
from app.core.probe import ProbeController
from app.core.state import MachineState


@pytest.fixture
def rig():
    state = MachineState()
    fake = FakeGRBL()
    adapter = GRBLAdapter(fake.transport, state, poll_interval=0.05)
    fake.transport.on_line = adapter._rx_queue.put
    adapter.connect()
    time.sleep(0.3)  # let the first status poll land
    yield fake, adapter, state
    adapter.close()


def test_status_polling_updates_state(rig):
    fake, adapter, state = rig
    s = state.snapshot()
    assert s.connected
    assert s.grbl_state == "Idle"
    assert s.mpos.x == 0.0


def test_jog_moves_position_and_can_be_cancelled(rig):
    fake, adapter, state = rig
    adapter.jog("X", 10.0, 6000)
    deadline = time.time() + 5
    while time.time() < deadline:
        if abs(state.snapshot().mpos.x - 10.0) < 0.5 and state.snapshot().grbl_state == "Idle":
            break
        time.sleep(0.02)
    assert abs(state.snapshot().mpos.x - 10.0) < 0.5


def test_jog_cancel_stops_motion(rig):
    fake, adapter, state = rig
    adapter.jog("X", 100.0, 500)   # slow, long move
    time.sleep(0.15)
    adapter.jog_cancel()
    deadline = time.time() + 3
    while state.snapshot().grbl_state != "Idle" and time.time() < deadline:
        time.sleep(0.02)
    x = state.snapshot().mpos.x
    assert 0.1 < x < 50.0  # moved partway, then stopped


def test_work_offset_via_g10(rig):
    fake, adapter, state = rig
    adapter.move_absolute(x=10, y=5, z=0, feedrate=6000)
    time.sleep(0.3)
    r = adapter.set_work_offset("G54", x=0, y=0, z=0)
    assert r.ok
    # L20: the offset must make the current position read 0,0,0
    assert fake.wco == [10.0, 5.0, 0.0]
    time.sleep(0.2)
    assert state.snapshot().wpos.x == pytest.approx(0.0, abs=0.01)


def test_probe_xy_zero_offset_and_compensation(rig):
    """X- probe, 6mm tool: contact center at raw=-20, part face at -17.

    G10 value v = sign*(radius - offset) must put the face at:
      offset 0 -> wco = -17 (face reads 0)
      offset 5 -> wco = -22 (face reads 5, zero pushed into material)
    """
    fake, adapter, state = rig
    pc = ProbeController(adapter)
    from app.core.probe import ProbeConfig

    fake.probe_result = -20.0
    r = pc.run_edge(ProbeConfig(direction="X-", tool_diameter=6.0, travel=-20))
    assert r.ok
    time.sleep(0.3)
    assert fake.wco[0] == pytest.approx(-17.0, abs=0.01)   # face is the zero

    fake.probe_result = -20.0
    r = pc.run_edge(ProbeConfig(direction="X-", tool_diameter=6.0, travel=-20, zero_offset=5.0))
    assert r.ok
    time.sleep(0.3)
    assert fake.wco[0] == pytest.approx(-22.0, abs=0.01)   # zero 5mm into material


def test_probe_reports_contact_position(rig):
    fake, adapter, state = rig
    fake.probe_result = -7.5
    pos = adapter.start_probe("Z", -20.0, 600)
    assert pos.z == pytest.approx(-7.5, abs=1e-6)


def test_probe_failure_raises(rig):
    fake, adapter, state = rig
    fake.probe_contact = False
    with pytest.raises(RuntimeError):
        adapter.start_probe("Z", -20.0, 600)
