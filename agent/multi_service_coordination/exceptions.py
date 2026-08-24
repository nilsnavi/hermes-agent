"""Sprint 1.3.15 — multi-service coordination exceptions.

Consistent fail-closed exception hierarchy.  Every exception is a subclass of
MultiServiceCoordError so a caller can catch the whole domain once.
"""
from __future__ import annotations


class MultiServiceCoordError(RuntimeError):
    """Base class for all multi-service coordination errors."""


class PlanInvalid(MultiServiceCoordError):
    """The multi-service plan is structurally invalid or frozen-mutated."""


class PlanExpired(MultiServiceCoordError):
    """The plan's expiry window has passed."""


class EligibilityDenied(MultiServiceCoordError):
    """At least one required child is not eligible (all-or-nothing)."""


class UnknownChildOutcome(MultiServiceCoordError):
    """A child returned UNKNOWN — never auto-retried, never treated as ALLOW."""


class LockAcquisitionFailed(MultiServiceCoordError):
    """A canonical lock could not be acquired; already-held locks are released."""


class BarrierBlocked(MultiServiceCoordError):
    """A prepare barrier child did not reach READY."""


class CoordinatorStateError(MultiServiceCoordError):
    """Illegal state transition in the global transaction state machine."""


class CompensationRequired(MultiServiceCoordError):
    """A partial failure demands deterministic compensation."""


class CompensationFailed(MultiServiceCoordError):
    """Compensation could not be completed / one child is rollback-unsupported."""


class ExecutionDisabled(MultiServiceCoordError):
    """Real multi-service execution is forbidden in Sprint 1.3.15."""


class DurableStateCorrupt(MultiServiceCoordError):
    """The durable coordination store is unreadable or structurally invalid."""


__all__ = [
    "BarrierBlocked",
    "CompensationFailed",
    "CompensationRequired",
    "CoordinatorStateError",
    "DurableStateCorrupt",
    "EligibilityDenied",
    "ExecutionDisabled",
    "LockAcquisitionFailed",
    "MultiServiceCoordError",
    "PlanExpired",
    "PlanInvalid",
    "UnknownChildOutcome",
]