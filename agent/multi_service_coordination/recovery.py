"""Sprint 1.3.15 — recovery classifier driven by durable evidence only.

Global recovery states:
    SAFE_TO_ABORT
    SAFE_TO_CONTINUE_VERIFY
    COMPENSATION_REQUIRED
    MANUAL_REVIEW_REQUIRED
    TERMINAL

Classification NEVER reads in-memory status strings as authority — it requires
durable journal/evidence.  UNKNOWN evidence => manual review.
"""
from __future__ import annotations

from enum import Enum


class RecoveryState(Enum):
    SAFE_TO_ABORT = "SAFE_TO_ABORT"
    SAFE_TO_CONTINUE_VERIFY = "SAFE_TO_CONTINUE_VERIFY"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    TERMINAL = "TERMINAL"
    UNKNOWN = "UNKNOWN"


# Journal types that represent durable terminal evidence.
_TERMINAL_EVENTS = {
    "GLOBAL_SIMULATED_COMMIT",
    "GLOBAL_FAILED",
    "COMPENSATION_FAILED",
    "MANUAL_REVIEW_REQUIRED",
}
_COMMIT_EVENTS = {"GLOBAL_SIMULATED_COMMIT"}
_COMPENSATION_EVENTS = {"COMPENSATION_REQUIRED", "CHILD_FAILED"}
_CLAIMED_EVENTS = {"GLOBAL_CLAIMED"}


def classify_recovery(journal_types: list[str], child_outcomes: dict[str, str] | None = None) -> RecoveryState:
    """Recovery classification from the durable event journal (evidence)."""
    if not journal_types:
        return RecoveryState.UNKNOWN
    # UNKNOWN outcome anywhere => fail closed to manual review.
    if child_outcomes and any(o == "UNKNOWN" for o in child_outcomes.values()):
        return RecoveryState.UNKNOWN
    if any(ev in _TERMINAL_EVENTS for ev in journal_types):
        if _COMMIT_EVENTS & set(journal_types):
            return RecoveryState.TERMINAL
        return RecoveryState.TERMINAL
    if any(ev in _COMPENSATION_EVENTS for ev in journal_types):
        return RecoveryState.COMPENSATION_REQUIRED
    if any(ev in _CLAIMED_EVENTS for ev in journal_types):
        # claimed but not terminated AND not yet verifying => ambiguous
        if any(ev in {"VERIFY_COMPLETED", "SIMULATION_STARTED"} for ev in journal_types):
            return RecoveryState.SAFE_TO_CONTINUE_VERIFY
        return RecoveryState.SAFE_TO_ABORT
    return RecoveryState.UNKNOWN


__all__ = ["RecoveryState", "classify_recovery"]