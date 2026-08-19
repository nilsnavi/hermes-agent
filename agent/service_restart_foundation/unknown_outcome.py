"""Sprint 1.3.12 — UNKNOWN_OUTCOME handling.

Critical restart states STOP_UNKNOWN / START_UNKNOWN: do NOT blindly start /
restart again. No auto-retry. Require reconcile / manual review / safe recovery.
"""
from __future__ import annotations

from enum import Enum


class OutcomeClass(Enum):
    HALT_STOP = "HALT_STOP"
    DO_NOT_BLIND_START = "DO_NOT_BLIND_START"
    DO_NOT_RESTART = "DO_NOT_RESTART"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    PROCEED = "PROCEED"
    UNKNOWN = "UNKNOWN"


class UnknownOutcomePolicy:
    """Policy for unknown restart outcomes. NEVER auto-retries."""

    AUTO_RETRY = False
    REQUIRES_MANUAL_REVIEW = True


def classify_outcome(state: str) -> OutcomeClass:
    """Classify a critical/unknown restart outcome into an action class."""
    s = (state or "").upper()
    if s == "STOP_UNKNOWN":
        return OutcomeClass.DO_NOT_BLIND_START
    if s == "START_UNKNOWN":
        return OutcomeClass.DO_NOT_RESTART
    if s == "STOP_REQUESTED":
        return OutcomeClass.HALT_STOP
    if s == "START_REQUESTED":
        return OutcomeClass.DO_NOT_RESTART
    if s in ("STOPPED", "STARTED", "STARTED_VERIFIED"):
        return OutcomeClass.PROCEED
    return OutcomeClass.MANUAL_REVIEW


__all__ = [
    "OutcomeClass",
    "UnknownOutcomePolicy",
    "classify_outcome",
]