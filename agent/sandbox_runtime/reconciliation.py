"""Pure, read-only post-crash state reconciliation."""
from enum import Enum
from typing import Any


class ReconciliationOutcome(str, Enum):
    UNCHANGED = "UNCHANGED"
    APPLIED = "APPLIED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    DIVERGED = "DIVERGED"
    UNKNOWN = "UNKNOWN"


def reconcile_state(before: Any, expected_after: Any, observed: Any) -> ReconciliationOutcome:
    """Classify observed state without mutating or invoking an adapter."""
    if observed is None:
        return ReconciliationOutcome.UNKNOWN
    if observed == before:
        return ReconciliationOutcome.UNCHANGED
    if observed == expected_after:
        return ReconciliationOutcome.APPLIED
    if isinstance(observed, (str, bytes)) and isinstance(expected_after, type(observed)):
        if observed and expected_after.startswith(observed):
            return ReconciliationOutcome.PARTIALLY_APPLIED
    return ReconciliationOutcome.DIVERGED
