"""Agent capability request contract and caller claims.

An ``AgentCapabilityIntent`` is the typed request that every agent run offers to
the security gate. It names WHO (agent/tenant/user), WHAT (task/step/run), and
WHICH capability + side-effect class is being requested. It carries NO verdict,
NO approval and NO right: authority is computed by the gate alone from the
mandatory pipeline components at admission time.

``CallerClaim`` is deliberately data-only. A caller may state anything it wants
in a claim (``approval=\"APPROVED\"``, ``allow=True``, ``verdict=\"PASS\"``,
``policy_result=...``, ``boundary_result=...``). The gate reads claims as data
(for audit) and NEVER uses them to authorize. This is the
"caller-supplied verdict/approval == DATA, not authority" invariant.
"""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import CallerVerdictRejected
from .status import SideEffectClass

_MAX_TEXT_LENGTH = 65_536
_IS_AUTHORITY = False  # declared once: claims carry no authority


def _require_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CallerVerdictRejected(f"{name} must be a non-empty string")
    if len(value) > _MAX_TEXT_LENGTH:
        raise CallerVerdictRejected(f"{name} exceeds the {_MAX_TEXT_LENGTH}-character limit")
    return value


def _require_opt_id(name: str, value: str) -> str:
    if value is None or value == "":
        return ""
    return _require_id(name, value)


@dataclass(frozen=True, slots=True)
class AgentCapabilityIntent:
    """Bounded, typed capability request offered to the gate for admission."""

    agent_id: str
    tenant_id: str
    user_id: str
    capability: str
    side_effect_class: SideEffectClass
    task_id: str = ""
    task_step_id: str = ""
    agent_run_id: str = ""
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        for name in ("agent_id", "tenant_id", "user_id", "capability"):
            object.__setattr__(self, name, _require_id(name, getattr(self, name)))
        for name in ("task_id", "task_step_id", "agent_run_id", "idempotency_key"):
            object.__setattr__(
                self, name, _require_opt_id(name, getattr(self, name))
            )
        if type(self.side_effect_class) is not SideEffectClass:
            raise CallerVerdictRejected(
                "side_effect_class must be an exact SideEffectClass value"
            )


# assert-compatible constant: claims can never act as authority.
CLAIMS_ARE_DATA = _IS_AUTHORITY


@dataclass(frozen=True, slots=True)
class CallerClaim:
    """Caller-supplied assertions. DATA ONLY: never inspected for authorization."""

    approval: str | None = None
    verdict: str | None = None
    allow: bool | None = None
    risk_score: float | None = None
    policy_result: str | None = None
    boundary_result: str | None = None
    runner_override: str | None = None

    @property
    def is_authority(self) -> bool:
        return _IS_AUTHORITY

    def as_audit_data(self) -> dict[str, object]:
        """Serialize the claim for audit as inert data (never read back for authz)."""
        return {
            "claim_approval": self.approval,
            "claim_verdict": self.verdict,
            "claim_allow": self.allow,
            "claim_risk_score": self.risk_score,
            "claim_policy_result": self.policy_result,
            "claim_boundary_result": self.boundary_result,
            "claim_runner_override": self.runner_override,
            "is_authority": _IS_AUTHORITY,
        }


__all__ = [
    "CLAIMS_ARE_DATA",
    "AgentCapabilityIntent",
    "CallerClaim",
]