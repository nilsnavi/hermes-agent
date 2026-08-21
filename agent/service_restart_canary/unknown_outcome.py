"""Sprint 1.3.13 — unknown outcome policy (no blind restart, no auto retry).

Critical states: after a restart command timeout / status unavailable, the
outcome is UNKNOWN. We must NOT issue a second restart. Reconciliation +
manual review only.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OutcomeClass(Enum):
    HALT_STOP = "HALT_STOP"
    DO_NOT_BLIND_START = "DO_NOT_BLIND_START"
    DO_NOT_RESTART = "DO_NOT_RESTART"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True)
class UnknownOutcomePolicy:
    # Never auto-retry a restart on unknown outcome.
    AUTO_RETRY: bool = False


def classify_outcome(status: str) -> OutcomeClass:
    s = status.upper()
    if s in ("STOP_REQUESTED", "STOPPING", "STOP_UNKNOWN"):
        return OutcomeClass.DO_NOT_BLIND_START
    if s in ("START_REQUESTED", "START_UNKNOWN", "STARTED"):
        return OutcomeClass.DO_NOT_RESTART
    if s in ("UNKNOWN_OUTCOME", "COMMAND_TIMEOUT", "CONNECTION_INTERRUPTED",
             "STATUS_UNAVAILABLE"):
        return OutcomeClass.MANUAL_REVIEW
    if s in ("OLD_PID_SURVIVES", "CRASH_AFTER_STOP"):
        return OutcomeClass.HALT_STOP
    # STOPPED / HEALTHY etc -> reconciled state, no restart needed
    return OutcomeClass.MANUAL_REVIEW


__all__ = ["OutcomeClass", "UnknownOutcomePolicy", "classify_outcome"]