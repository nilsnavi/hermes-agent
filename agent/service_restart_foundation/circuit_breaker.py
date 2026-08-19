"""Sprint 1.3.12 — restart circuit breaker (foundation, tests only).

Future breaker triggers: UNKNOWN_OUTCOME, orphan detected, start health fail,
rollback failure, identity mismatch after start. In 1.3.12 the breaker is wired
only for shadow/tests; it never trips on a real production restart (there are none).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BreakerState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


# Conditions that must trip the breaker.
BREAKER_TRIGGERS = {
    "UNKNOWN_OUTCOME",
    "ORPHAN_DETECTED",
    "START_HEALTH_FAIL",
    "ROLLBACK_FAILURE",
    "IDENTITY_MISMATCH_AFTER_START",
}


@dataclass
class RestartCircuitBreaker:
    state: BreakerState = BreakerState.CLOSED
    tripped_by: str = ""

    def trip(self, reason: str) -> None:
        if reason not in BREAKER_TRIGGERS:
            reason = "UNKNOWN_OUTCOME"
        self.state = BreakerState.OPEN
        self.tripped_by = reason

    def allow(self) -> bool:
        return self.state == BreakerState.CLOSED

    def reset(self) -> None:
        self.state = BreakerState.CLOSED
        self.tripped_by = ""


def breaker_must_trip(signal: str) -> bool:
    """True when the signal belongs to the breaker trigger set."""
    return signal in BREAKER_TRIGGERS


__all__ = [
    "BREAKER_TRIGGERS",
    "BreakerState",
    "RestartCircuitBreaker",
    "breaker_must_trip",
]