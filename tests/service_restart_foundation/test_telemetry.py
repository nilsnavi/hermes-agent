"""Sprint 1.3.12 — telemetry counters (bounded, no high-cardinality IDs)."""
from __future__ import annotations

from agent.service_restart_foundation import telemetry


class TestTelemetry:
    def test_unknown_counter_rejected(self):
        telemetry.reset()
        try:
            telemetry.inc("no_such_counter")
            assert False, "should raise"
        except KeyError:
            pass

    def test_counter_inc_snapshot(self):
        telemetry.reset()
        telemetry.inc(telemetry.C_REQUESTED, 3)
        snap = telemetry.snapshot()
        assert snap[telemetry.C_REQUESTED] == 3
        assert telemetry.get(telemetry.C_REQUESTED) == 3

    def test_execution_blocked_counter_present(self):
        telemetry.reset()
        assert telemetry.get(telemetry.C_EXECUTION_BLOCKED) == 0