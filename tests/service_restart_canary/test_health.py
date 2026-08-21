"""Test stabilization health window: T+0/2/5/10 all HEALTHY -> stable."""
from agent.service_restart_canary.stabilization import (evaluate_stabilization, sample,
                                                         STABILIZATION_OFFSETS)


def test_stabilized_ok():
    samples = [sample(o, "HEALTHY") for o in STABILIZATION_OFFSETS]
    ok, _ = evaluate_stabilization(samples)
    assert ok is True


def test_incomplete_window():
    samples = [sample(0.0, "HEALTHY"), sample(2.0, "HEALTHY")]
    ok, why = evaluate_stabilization(samples)
    assert ok is False
    assert why == "incomplete_window"


def test_unhealthy():
    samples = [sample(0.0, "HEALTHY"), sample(2.0, "HEALTHY"),
               sample(5.0, "DEGRADED"), sample(10.0, "HEALTHY")]
    ok, why = evaluate_stabilization(samples)
    assert ok is False
    assert why.startswith("not_healthy")


def test_unknown_blocks_commit():
    samples = [sample(0.0, "UNKNOWN"), sample(2.0, "HEALTHY"),
               sample(5.0, "HEALTHY"), sample(10.0, "HEALTHY")]
    ok, _ = evaluate_stabilization(samples)
    assert ok is False


def test_offsets_exact():
    assert STABILIZATION_OFFSETS == (0.0, 2.0, 5.0, 10.0)