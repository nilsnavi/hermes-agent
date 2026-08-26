"""Execution-boundary status vocabulary for the security gate.

Enums that classify what an admission request does (side-effect class), what the
single-instance admission gate may conclude (outcome), and the precise disposition
that produced the conclusion. These are pure, immutable classification tokens; a
disposition is a control-plane reason code, never a grant.
"""

from __future__ import annotations

from enum import Enum


class SideEffectClass(Enum):
    READ_ONLY = "read_only"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    SERVICE_MUTATION = "service_mutation"
    SYSTEM_CONTROL = "system_control"
    UNKNOWN = "unknown"


class AdmissionOutcome(Enum):
    ALLOW_READ_ONLY = "allow_read_only"
    ALLOW_SHADOW = "allow_shadow"
    DENY = "deny"
    HUMAN_REVIEW = "human_review"


class Disposition(Enum):
    ADMITTED = "admitted"
    DENIED = "denied"
    REVALIDATE_REQUIRED = "revalidate_required"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    MISSING_EVIDENCE = "missing_evidence"
    SIDE_EFFECT_UNKNOWN = "side_effect_unknown"
    COMPONENT_MISSING = "component_missing"
    REGISTRY_DRIFT = "registry_drift"
    CALLER_VERDICT_REJECTED = "caller_verdict_rejected"
    SEAL_VIOLATION = "seal_violation"


# Dispositions that must never proceed to execution (fail-closed): absence of
# decisive positive evidence is a denial, never a green light.
NON_EXECUTABLE_DISPOSITIONS = frozenset(
    {
        Disposition.REVALIDATE_REQUIRED,
        Disposition.UNKNOWN,
        Disposition.TIMEOUT,
        Disposition.MISSING_EVIDENCE,
        Disposition.COMPONENT_MISSING,
        Disposition.REGISTRY_DRIFT,
        Disposition.CALLER_VERDICT_REJECTED,
        Disposition.SEAL_VIOLATION,
        Disposition.DENIED,
        Disposition.SIDE_EFFECT_UNKNOWN,  # HUMAN_REVIEW is not executable either
    }
)

# Side-effect classes that no read-only/shadow admission may ever allow through.
MUTATION_CLASSES = frozenset(
    {
        SideEffectClass.WRITE,
        SideEffectClass.EXECUTE,
        SideEffectClass.SERVICE_MUTATION,
        SideEffectClass.SYSTEM_CONTROL,
    }
)


__all__ = [
    "AdmissionOutcome",
    "Disposition",
    "MUTATION_CLASSES",
    "NON_EXECUTABLE_DISPOSITIONS",
    "SideEffectClass",
]