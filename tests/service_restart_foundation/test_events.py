"""Sprint 1.3.12 — append-only analysis events (no mutation events exist)."""
from __future__ import annotations

import pytest

from agent.service_restart_foundation import events


class TestEvents:
    def test_record_event_append_only(self):
        log = events.RestartEventLog()
        e1 = log.record(events.SERVICE_RESTART_ELIGIBILITY_EVALUATED, "svc")
        e2 = log.record(events.SERVICE_RESTART_EXECUTION_BLOCKED, "svc")
        snap = log.snapshot()
        assert [e.seq for e in snap] == [1, 2]
        assert len(log) == 2

    def test_unknown_kind_rejected(self):
        log = events.RestartEventLog()
        with pytest.raises(ValueError):
            log.record("SERVICE_RESTART_SOMETHING_EXECUTED", "svc")

    def test_no_mutation_event_types_registered(self):
        # the sprint must expose no production mutation event names
        assert events.MUTATION_EVENT_NAMES == ()

    def test_emit_and_mutation_count(self):
        events.emit(events.SERVICE_RESTART_PLAN_CREATED, "svc", detail="d1")
        assert events.mutation_event_count() == 0