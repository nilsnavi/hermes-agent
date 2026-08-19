"""Sprint 1.3.12 — restart rollback planning (analysis only, no production rollback).

Restart rollback is fundamentally harder than reload rollback. Strategies are
modelled; no production rollback runs in 1.3.12.

RESTART-AS-ROLLBACK IS HARD DENIED: "restart again" is an auto-retry, not a
rollback. No RESTART_SAME_VERSION strategy exists and it must never be admitted.
"""
from __future__ import annotations

from enum import Enum


class RollbackStrategy(Enum):
    RECONCILE_CURRENT_STATE = "RECONCILE_CURRENT_STATE"
    START_PREVIOUS_VERSION = "START_PREVIOUS_VERSION"
    RESTART_PREVIOUS_VERSION = "RESTART_PREVIOUS_VERSION"
    RESTORE_CONFIG_THEN_START = "RESTORE_CONFIG_THEN_START"
    OPERATOR_INTERVENTION = "OPERATOR_INTERVENTION"
    UNSUPPORTED = "UNSUPPORTED"

    # RESTART_SAME_VERSION is deliberately NOT present: it is auto-retry, not
    # a rollback.


# There is intentionally no RESTART_SAME_VERSION member.
RESTART_SAME_VERSION = None


def restart_as_rollback_denied(strategy: RollbackStrategy | None = None) -> bool:
    """True ALWAYS — using a restart as a rollback (restart-again) is hard denied."""
    return True


def plan_rollback(strategy: RollbackStrategy = RollbackStrategy.OPERATOR_INTERVENTION) -> dict:
    """Analyse a rollback strategy (no production mutation)."""
    return {
        "strategy": strategy.value,
        "production_mutation": 0,
        "restart_retry": False,
        "requires_operator": strategy in (
            RollbackStrategy.OPERATOR_INTERVENTION,
            RollbackStrategy.UNSUPPORTED,
        ),
    }


def rollback_proven(strategy: RollbackStrategy) -> bool:
    """A rollback is proven only for non-UNSUPPORTED strategies in 1.3.12 analysis."""
    return strategy != RollbackStrategy.UNSUPPORTED


__all__ = [
    "RESTART_SAME_VERSION",
    "RollbackStrategy",
    "plan_rollback",
    "restart_as_rollback_denied",
    "rollback_proven",
]