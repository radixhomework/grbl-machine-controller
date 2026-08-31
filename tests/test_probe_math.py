"""Probe compensation math (§6): true edge = probed center - radius * sign."""

import pytest

from app.core.probe import ProbeConfig, ProbeController


@pytest.mark.parametrize("direction,diameter,raw,expected", [
    ("X-", 6.0, -10.0, -7.0),    # approaching left edge going X-: edge is at raw + r
    ("X+", 6.0, 10.0, 7.0),      # approaching right edge going X+: edge at raw - r
    ("Y-", 3.175, -5.0, -3.4125),
    ("Y+", 0.0, 12.0, 12.0),     # zero-diameter: no compensation
])
def test_compensate(direction, diameter, raw, expected):
    assert ProbeController.compensate(raw, diameter, direction) == pytest.approx(expected)


def test_probe_config_defaults():
    cfg = ProbeConfig(direction="X-", tool_diameter=6.0)
    assert cfg.fast_feed == 300.0
    assert cfg.slow_feed == 30.0
    assert cfg.retract == 2.0
