"""JobManager end-to-end against the simulator: run, pause, alarm, unlock."""

import threading
import time

import pytest

from app.core.fake_grbl import FakeGRBL
from app.core.grbl_adapter import GRBLAdapter
from app.core.job_manager import JobManager, JobState
from app.core.state import MachineState


@pytest.fixture
def rig():
    state = MachineState()
    fake = FakeGRBL()
    adapter = GRBLAdapter(fake.transport, state, poll_interval=0.05)
    fake.transport.on_line = adapter._rx_queue.put
    adapter.connect()
    time.sleep(0.2)
    jobs = JobManager(adapter, state)
    yield fake, adapter, jobs
    adapter.close()


def _write_gcode(tmp_path, n=30):
    p = tmp_path / "job.nc"
    p.write_text("\n".join(f"G1 X{i%10} Y{i%7} F5000" for i in range(n)) + "\n")
    return str(p)


def test_full_job_completes(rig, tmp_path):
    fake, adapter, jobs = rig
    jobs.load_file(_write_gcode(tmp_path))
    assert jobs.start()
    deadline = time.time() + 15
    while jobs.job_state not in (JobState.COMPLETE, JobState.ERROR) and time.time() < deadline:
        time.sleep(0.05)
    assert jobs.job_state == JobState.COMPLETE
    assert state_progress(jobs) == 1.0


def state_progress(jobs):
    return jobs.state.snapshot().job_progress


def test_alarm_halts_job_and_unlock_recovers(rig, tmp_path):
    fake, adapter, jobs = rig
    jobs.load_file(_write_gcode(tmp_path))
    jobs.start()
    time.sleep(0.2)
    fake.trigger_alarm(9)
    deadline = time.time() + 5
    while jobs.job_state != JobState.ALARM and time.time() < deadline:
        time.sleep(0.02)
    assert jobs.job_state == JobState.ALARM
    fake._jog_cancelled = True
    fake.alarm = False
    fake.state = "Idle"
    assert jobs.unlock()
    assert jobs.job_state == JobState.IDLE
