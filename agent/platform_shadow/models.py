"""Shadow data models (Phase 7 §3, §4, §14).

All shadow types are IMMUTABLE DATA. There is deliberately NO field that can
carry a credential, secret, execution/approval token, adapter, executor or
authority reference, and NO method that turns a shadow result into an override
or a grant. Shadow output can never change production output.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


def _req(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


class ShadowSamplingMode(Enum):
    OFF = "off"
    SAMPLE = "sample"
    FULL_SHADOW = "full_shadow"


class ComparisonClass(Enum):
    MATCH = "match"
    PARTIAL_MATCH = "partial_match"
    DIFFERENT_AGENT = "different_agent"
    DIFFERENT_PLAN = "different_plan"
    DIFFERENT_DISPOSITION = "different_disposition"
    SHADOW_DENIED = "shadow_denied"
    SHADOW_UNKNOWN = "shadow_unknown"
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True, slots=True)
class ShadowTaskEnvelope:
    """Immutable snapshot of ONE inbound production task/event copy (data only).

    Holds NO credentials, secrets, tokends, adapters or executor references. It
    is the ONLY production touch-point the shadow runtime ever receives, and it
    is a copy -- the runtime can neither return nor mutate a production object.
    """

    shadow_id: str
    source_request_id: str
    tenant_id: str
    user_id: str
    task_kind: str
    input_digest: str
    received_at: float
    sampling_reason: str
    production_context_digest: str
    baseline_version: str

    def __post_init__(self) -> None:
        for name in (
            "shadow_id", "source_request_id", "tenant_id", "user_id", "task_kind",
            "input_digest", "sampling_reason", "production_context_digest",
            "baseline_version",
        ):
            object.__setattr__(self, name, _req(name, getattr(self, name)))
        if not isinstance(self.received_at, (int, float)) or not float(self.received_at) >= 0:
            raise ValueError("received_at must be a non-negative timestamp")

    def to_dict(self) -> dict[str, object]:
        return {
            "shadow_id": self.shadow_id,
            "source_request_id": self.source_request_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "task_kind": self.task_kind,
            "input_digest": self.input_digest,
            "received_at": self.received_at,
            "sampling_reason": self.sampling_reason,
            "production_context_digest": self.production_context_digest,
            "baseline_version": self.baseline_version,
        }


@dataclass(frozen=True, slots=True)
class ShadowDecision:
    """The full shadow result for one sampled task (DATA ONLY, never authority)."""

    shadow_id: str
    task_id: str
    plan_digest: str
    selected_agent: str
    agent_observation: str
    supervisor_disposition: str
    confidence: float
    policy_disposition: str
    boundary_disposition: str
    memory_digest: str
    duration_ms: float
    comparison_class: ComparisonClass
    audit_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "shadow_id": self.shadow_id,
            "task_id": self.task_id,
            "plan_digest": self.plan_digest,
            "selected_agent": self.selected_agent,
            "agent_observation": self.agent_observation,
            "supervisor_disposition": self.supervisor_disposition,
            "confidence": self.confidence,
            "policy_disposition": self.policy_disposition,
            "boundary_disposition": self.boundary_disposition,
            "memory_digest": self.memory_digest,
            "duration_ms": self.duration_ms,
            "comparison_class": self.comparison_class.value,
            "audit_id": self.audit_id,
        }

    # No method here can influence production: this is query/binding data only.
    def never_authority(self) -> bool:
        return True  # documented marker used by the isolation tests


__all__ = [
    "ComparisonClass",
    "ShadowDecision",
    "ShadowSamplingMode",
    "ShadowTaskEnvelope",
]