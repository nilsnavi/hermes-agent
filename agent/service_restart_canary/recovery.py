"""Sprint 1.3.13 — single aux service restart canary (recovery).

Recovery decision from durable evidence only. Decision outcomes:
RECONCILE_RUNNING_HEALTHY / RECONCILE_STOPPED / MANUAL_REVIEW / HALT.
No blind restart. No automatic second restart. Restart-as-rollback denied.
"""
from __future__ import annotations

from enum import Enum


class RecoveryDecision(Enum):
    RECONCILE_RUNNING_HEALTHY = "RECONCILE_RUNNING_HEALTHY"
    RECONCILE_STOPPED = "RECONCILE_STOPPED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    HALT = "HALT"


def recovery_decision(state: str, old_gone: bool, new_healthy: bool,
                      durable_evidence: str = "") -> RecoveryDecision:
    """Decide from durable evidence only. Never blind-restarts."""
    ev = (durable_evidence or "").upper()
    if ev in ("", "UNKNOWN"):
        return RecoveryDecision.MANUAL_REVIEW
    if ev == "UNKNOWN_OUTCOME":
        return RecoveryDecision.MANUAL_REVIEW
    if ev == "OLD_PID_SURVIVES":
        return RecoveryDecision.HALT
    # No new healthy process -> do not start again blindly, manual review.
    if not new_healthy and not old_gone:
        return RecoveryDecision.HALT
    if new_healthy:
        return RecoveryDecision.RECONCILE_RUNNING_HEALTHY
    return RecoveryDecision.RECONCILE_STOPPED


def restart_as_rollback_denied() -> bool:
    """A failed restart must not be answered with another restart. Hard DENY."""
    return True


__all__ = ["RecoveryDecision", "recovery_decision", "restart_as_rollback_denied"]