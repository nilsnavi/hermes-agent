"""Sprint 1.3.12 — crash recovery decision (fake/deterministic only).

Recovery decision is made from durable evidence only. Never blindly start.
No real kill/restart in 1.3.12.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CrashPoint(Enum):
    AFTER_STOP_REQUEST = "after_stop_request"
    AFTER_OLD_PID_EXIT = "after_old_pid_exit"
    DURING_QUIESCENCE = "during_quiescence"
    BEFORE_START = "before_start"
    AFTER_START_REQUEST = "after_start_request"
    AFTER_NEW_PID = "after_new_pid"
    BEFORE_HEALTH = "before_health"
    AFTER_HEALTH = "after_health"


class RecoveryDecision(Enum):
    RECONCILE = "RECONCILE_CURRENT_STATE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    HALT = "HALT"
    RECOVER = "RECOVER_FROM_DURABLE_EVIDENCE"


@dataclass(frozen=True)
class RecoveryResult:
    decision: RecoveryDecision
    reason: str = ""


def recovery_decision(
    crash_point: CrashPoint,
    durable_evidence: str = "",
    old_pid_alive: bool = False,
    new_pid_alive: bool = False,
) -> RecoveryDecision:
    """Decide recovery from durable evidence only. Always fail-closed."""
    ev = (durable_evidence or "").upper()

    # Anything we cannot prove from durable evidence -> manual review.
    if ev in ("", "UNKNOWN"):
        return RecoveryDecision.MANUAL_REVIEW

    # Old PID still alive after a stop request was issued -> halt, do not start.
    if crash_point in (CrashPoint.AFTER_STOP_REQUEST,
                       CrashPoint.AFTER_OLD_PID_EXIT) and old_pid_alive:
        return RecoveryDecision.HALT

    # A new PID appeared but state is uncertain -> reconcile, never auto-restart.
    if crash_point in (CrashPoint.AFTER_NEW_PID,
                       CrashPoint.BEFORE_HEALTH) and new_pid_alive:
        return RecoveryDecision.MANUAL_REVIEW

    # Otherwise: reconcile current state from durable evidence.
    return RecoveryDecision.RECONCILE


__all__ = [
    "CrashPoint",
    "RecoveryDecision",
    "RecoveryResult",
    "recovery_decision",
]