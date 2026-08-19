"""Sprint 1.3.12 — restart circuit breaker (foundation, tests only)."""
from __future__ import annotations

from agent.service_restart_foundation.circuit_breaker import (
    BREAKER_TRIGGERS,
    BreakerState,
    RestartCircuitBreaker,
    breaker_must_trip,
)


class TestCircuitBreaker:
    def test_closed_by_default(self):
        cb = RestartCircuitBreaker()
        assert cb.state == BreakerState.CLOSED
        assert cb.allow() is True

    def test_unknown_outcome_trips(self):
        cb = RestartCircuitBreaker()
        cb.trip("UNKNOWN_OUTCOME")
        assert cb.state == BreakerState.OPEN
        assert cb.allow() is False

    def test_orphan_detected_trips(self):
        cb = RestartCircuitBreaker()
        cb.trip("ORPHAN_DETECTED")
        assert cb.state == BreakerState.OPEN

    def test_identity_mismatch_trips(self):
        cb = RestartCircuitBreaker()
        cb.trip("IDENTITY_MISMATCH_AFTER_START")
        assert cb.state == BreakerState.OPEN

    def test_reset_closes(self):
        cb = RestartCircuitBreaker()
        cb.trip("START_HEALTH_FAIL")
        cb.reset()
        assert cb.state == BreakerState.CLOSED

    def test_triggers_covered(self):
        for trig in ("UNKNOWN_OUTCOME", "ORPHAN_DETECTED", "START_HEALTH_FAIL",
                     "ROLLBACK_FAILURE", "IDENTITY_MISMATCH_AFTER_START"):
            assert breaker_must_trip(trig) is True