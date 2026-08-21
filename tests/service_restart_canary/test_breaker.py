"""Test circuit breaker: opens on safety violations, blocks further restart."""
from agent.service_restart_canary.breaker import RestartCircuitBreaker, BreakerState, TRIP_REASONS


def test_default_closed():
    b = RestartCircuitBreaker()
    assert b.open() is False
    assert b.state == BreakerState.CLOSED


def test_trip():
    b = RestartCircuitBreaker()
    b.trip("UNKNOWN_OUTCOME")
    assert b.open() is True
    assert b.reason == "UNKNOWN_OUTCOME"


def test_trip_invalid_reason_defaults_unknown():
    b = RestartCircuitBreaker()
    b.trip("garbage")
    assert b.reason == "UNKNOWN_OUTCOME"


def test_trip_reasons_contain_all_violations():
    for r in ("UNKNOWN_OUTCOME", "OLD_PID_SURVIVES", "ORPHAN_DETECTED", "QUIESCENCE_FAILURE",
              "START_TIMEOUT", "WRONG_NEW_EXECUTABLE", "WRONG_NEW_USER_CGROUP",
              "HEALTH_FAILURE", "ROLLBACK_FAILURE", "IDENTITY_MISMATCH"):
        assert r in TRIP_REASONS


def test_reset():
    b = RestartCircuitBreaker()
    b.trip("HEALTH_FAILURE")
    b.reset()
    assert b.open() is False
    assert b.reason == ""
