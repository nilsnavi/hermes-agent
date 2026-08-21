"""Sprint 1.3.13 — single aux service restart canary (circuit breaker).

Opens immediately on any safety violation; open breaker -> further restart
adapter calls denied (adapter=0).
"""
from __future__ import annotations

from enum import Enum


class BreakerState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"


TRIP_REASONS = {
    "UNKNOWN_OUTCOME",
    "OLD_PID_SURVIVES",
    "ORPHAN_DETECTED",
    "QUIESCENCE_FAILURE",
    "START_TIMEOUT",
    "WRONG_NEW_EXECUTABLE",
    "WRONG_NEW_USER_CGROUP",
    "HEALTH_FAILURE",
    "ROLLBACK_FAILURE",
    "IDENTITY_MISMATCH",
    "PORT_WRONG_OWNER",
}


class RestartCircuitBreaker:
    def __init__(self) -> None:
        self._state = BreakerState.CLOSED
        self._reason = ""

    @property
    def state(self) -> BreakerState:
        return self._state

    @property
    def reason(self) -> str:
        return self._reason

    def open(self) -> bool:
        return self._state == BreakerState.OPEN

    def trip(self, reason: str) -> None:
        self._state = BreakerState.OPEN
        self._reason = reason if reason in TRIP_REASONS else "UNKNOWN_OUTCOME"

    def reset(self) -> None:
        self._state = BreakerState.CLOSED
        self._reason = ""


def must_trip(signal: str) -> bool:
    return signal in TRIP_REASONS


__all__ = ["BreakerState", "RestartCircuitBreaker", "TRIP_REASONS", "must_trip"]