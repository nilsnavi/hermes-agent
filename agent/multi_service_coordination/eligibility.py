"""Sprint 1.3.15 — all-or-nothing eligibility aggregation.

The coordinator aggregates decisions from EXISTING per-service policy layers.
It never creates a parallel policy engine and never converts a DENY into an
ALLOW.

Rules:
    child DENY     -> parent DENY
    child UNKNOWN  -> parent DENY / REVALIDATE_REQUIRED
    child ALLOW    -> counts as ALLOW (all children ALLOW => parent ALLOW)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChildVerdict(Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    UNKNOWN = "UNKNOWN"


class AggregationReason(Enum):
    ALLOWED = "ALLOWED"
    CHILD_DENIED = "CHILD_DENIED"
    CHILD_UNKNOWN = "CHILD_UNKNOWN"
    REVALIDATE_REQUIRED = "REVALIDATE_REQUIRED"


def evaluate_child(decision: object) -> ChildVerdict:
    """Normalize an arbitrary per-service policy verdict to a 3-value verdict.

    Accepts: ChildVerdict, "ALLOW"/"DENY"/"UNKNOWN", True/False, or an object
    with a ``allowed`` attribute / ``reason``.  Anything not clearly ALLOW is
    DENY or UNKNOWN (fail closed).
    """
    if decision is None:
        return ChildVerdict.UNKNOWN
    if isinstance(decision, ChildVerdict):
        return decision
    if isinstance(decision, bool):
        return ChildVerdict.ALLOW if decision else ChildVerdict.DENY
    if isinstance(decision, str):
        upper = decision.upper()
        if upper == "ALLOW":
            return ChildVerdict.ALLOW
        if upper == "UNKNOWN":
            return ChildVerdict.UNKNOWN
        return ChildVerdict.DENY
    allowed = getattr(decision, "allowed", None)
    if allowed is not None:
        return ChildVerdict.ALLOW if bool(allowed) else ChildVerdict.DENY
    return ChildVerdict.UNKNOWN


@dataclass
class Aggregation:
    """Result of aggregating every child's eligibility."""

    child_verdicts: dict[str, ChildVerdict]
    reason: AggregationReason
    denied_children: tuple[str, ...] = ()
    unknown_children: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.reason == AggregationReason.ALLOWED


def aggregate_eligibility(child_decisions: dict[str, object]) -> Aggregation:
    """All children must be ALLOW.  Any DENY => DENY.  Any UNKNOWN => DENY."""
    verdicts = {sid: evaluate_child(v) for sid, v in child_decisions.items()}
    denied = tuple(sid for sid, v in verdicts.items() if v == ChildVerdict.DENY)
    unknown = tuple(sid for sid, v in verdicts.items() if v == ChildVerdict.UNKNOWN)
    if denied:
        return Aggregation(verdicts, AggregationReason.CHILD_DENIED, denied, unknown)
    if unknown:
        return Aggregation(
            verdicts, AggregationReason.REVALIDATE_REQUIRED, (), unknown
        )
    return Aggregation(verdicts, AggregationReason.ALLOWED)


__all__ = [
    "Aggregation",
    "AggregationReason",
    "ChildVerdict",
    "aggregate_eligibility",
    "evaluate_child",
]