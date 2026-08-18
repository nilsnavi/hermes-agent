"""Capability Router data model (Sprint 1.3.0 §3, §4, §10 + 1.3.1 §1, §2).

Pure data model — nothing here executes, switches or calls tools:

- :class:`CapabilityRequirement` (§3) — what an intent/subtype NEEDS
  from the V2 surface (capability, access mode, side effect,
  idempotency, network policy, approval policy, max tool calls).
- :class:`CapabilityDescriptor` (§4) — the REGISTRY FACT for one
  verified tool (capability, tool_name, verified, side_effect,
  idempotent, network, approval_required, timeout, health_dependency,
  health_requirement). A descriptor can never lower the risk reported
  by intent classification (§25).
- :class:`CapabilityRouteDecision` (§10) — one routing decision:
  route (V2 | LEGACY | DENY), intent, subtype, capability, tool,
  policy, reason, confidence + shadow-comparison evidence against the
  legacy (1.2.4) decision (route/tool/reason/subtype match flags).
- :class:`PolicyDecision` (Sprint 1.3.1 §1) — the canonical policy
  result of :meth:`CapabilityPolicyEngine.evaluate` with ALL mandatory
  fields: route, reason_code, risk_class, capability, tool,
  rollout_mode, health_state, confidence, policy_version + a bounded
  evaluated-checks trace (§22).

Reason taxonomy (Sprint 1.3.1 §2): :class:`ReasonCode` carries the
canonical deny/block reason codes. No free-text reason is ever used as
the primary decision key. ``PolicyReason`` remains as a legacy alias so
existing imports keep resolving; its VALUES are the canonical codes.

No raw prompt / authorization / tool args / full metadata ever enter
a decision object.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .capabilities import (
    AccessMode,
    ApprovalPolicy,
    Capability,
    CapabilityRoute,
    HealthRequirement,
    NetworkPolicy,
    RiskClass,
)


class ReasonCode:
    """Canonical deny/block reason taxonomy (Sprint 1.3.1 §2).

    Values are the canonical codes — never free text. ``ALLOWED`` marks
    the allow path (the decision reason_code is None then). The list
    below is the §2 canonical set plus the capability-specific gate
    codes the verified 1.2.x contracts need (ALLOWLIST_MISS /
    SUBTYPE_NOT_ALLOWED / QUERY_INVALID / ROLLOUT_LIMIT) — they are
    normalized codes, not free text.
    """

    # ── §2 canonical set ──────────────────────────────────────────
    UNSAFE_INTENT = "UNSAFE_INTENT"
    MIXED_UNSAFE_INTENT = "MIXED_UNSAFE_INTENT"
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    CAPABILITY_UNVERIFIED = "CAPABILITY_UNVERIFIED"
    TOOL_UNVERIFIED = "TOOL_UNVERIFIED"
    TOOL_RISK_MISMATCH = "TOOL_RISK_MISMATCH"
    NETWORK_NOT_ALLOWED = "NETWORK_NOT_ALLOWED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    HEALTH_UNAVAILABLE = "HEALTH_UNAVAILABLE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    AMBIGUOUS_INTENT = "AMBIGUOUS_INTENT"
    ROLLOUT_DISABLED = "ROLLOUT_DISABLED"
    SOURCE_NOT_ALLOWED = "SOURCE_NOT_ALLOWED"
    SECRET_QUERY = "SECRET_QUERY"
    FILESYSTEM_NOT_ALLOWED = "FILESYSTEM_NOT_ALLOWED"
    WEB_NOT_ALLOWED = "WEB_NOT_ALLOWED"
    POLICY_INTERNAL_ERROR = "POLICY_INTERNAL_ERROR"
    # ── capability-specific gate codes (verified 1.2.x contracts) ─
    ALLOWLIST_MISS = "ALLOWLIST_MISS"
    SUBTYPE_NOT_ALLOWED = "SUBTYPE_NOT_ALLOWED"
    QUERY_INVALID = "QUERY_INVALID"
    ROLLOUT_LIMIT = "ROLLOUT_LIMIT"
    ALLOWED = "ALLOWED"

    #: All canonical codes (for validation/fail-closed checks).
    ALL = frozenset({v for k, v in vars().items() if k.isupper()})

    # ── legacy aliases (Sprint 1.3.0 names → canonical values) ────
    # Kept so existing imports/tests comparing against the old names
    # keep resolving; the VALUES are the canonical 1.3.1 codes (§26:
    # reason codes may become normalized, the semantic decision stays).
    UNSUPPORTED_CAPABILITY = CAPABILITY_UNSUPPORTED
    UNVERIFIED_TOOL = TOOL_UNVERIFIED
    SIDE_EFFECT_VIOLATION = TOOL_RISK_MISMATCH
    RISK_ESCALATION = TOOL_RISK_MISMATCH
    NETWORK_VIOLATION = NETWORK_NOT_ALLOWED
    HEALTH_UNKNOWN = HEALTH_UNAVAILABLE
    AMBIGUOUS = AMBIGUOUS_INTENT
    POLICY_DISABLED = ROLLOUT_DISABLED


#: Legacy alias — existing imports of ``PolicyReason`` keep resolving;
#: values are the canonical Sprint 1.3.1 codes.
PolicyReason = ReasonCode


@dataclass(frozen=True)
class CapabilityRequirement:
    """§3 — one intent/subtype's requirement on the V2 surface."""

    capability: Capability
    access_mode: AccessMode = AccessMode.READ_ONLY
    side_effect: str = "NONE"  # ExpectedSideEffect-compatible value
    idempotency_required: bool = True
    network_policy: NetworkPolicy = NetworkPolicy.LOCAL_ONLY
    approval_policy: ApprovalPolicy = ApprovalPolicy.NONE
    max_tool_calls: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability.value,
            "access_mode": self.access_mode.value,
            "side_effect": self.side_effect,
            "idempotency_required": self.idempotency_required,
            "network_policy": self.network_policy.value,
            "approval_policy": self.approval_policy.value,
            "max_tool_calls": self.max_tool_calls,
        }


@dataclass(frozen=True)
class CapabilityDescriptor:
    """§4 — static registry fact for one verified tool.

    Sprint 1.3.1 §6 adds ``health_requirement`` — what the descriptor
    requires from the dependency health snapshot (HEALTHY default for
    the production read surface).
    """

    capability: Capability
    tool_name: str
    verified: bool = True
    side_effect: str = RiskClass.READ_ONLY.value  # RiskClass value
    idempotent: bool = True
    network: bool = False
    approval_required: bool = False
    timeout: float = 2.0
    health_dependency: str = "gateway"  # "gateway" | "search_source"
    health_requirement: HealthRequirement = HealthRequirement.HEALTHY
    max_tool_calls: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability.value,
            "tool_name": self.tool_name,
            "verified": self.verified,
            "side_effect": self.side_effect,
            "idempotent": self.idempotent,
            "network": self.network,
            "approval_required": self.approval_required,
            "timeout": self.timeout,
            "health_dependency": self.health_dependency,
            "health_requirement": self.health_requirement.value,
            "max_tool_calls": self.max_tool_calls,
        }


@dataclass(frozen=True)
class ResolvedCapability:
    """Resolver output: requirement + the per-request verified tool."""

    requirement: CapabilityRequirement
    tool: str


@dataclass
class CapabilityRouteDecision:
    """§10 — one capability routing decision.

    ``reason`` is the :class:`PolicyReason` value when the route is
    NOT V2 (None when allowed). Shadow-comparison fields
    (legacy_route / legacy_tool / legacy_reason / legacy_subtype and
    the match flags) are filled by the router when a legacy decision
    is available for comparison (§13).
    """

    route: CapabilityRoute
    intent: str
    subtype: Optional[str] = None
    capability: Optional[Capability] = None
    tool: Optional[str] = None
    policy: str = "cap-policy-v1"
    reason: Optional[str] = None
    confidence: Optional[float] = None
    # Sprint 1.3.1 §1 — canonical decision fields on the route decision.
    risk_class: Optional[str] = None
    rollout_mode: str = "off"
    health_state: str = "UNKNOWN"
    policy_version: str = "cap-policy-v1"
    # ── shadow comparison evidence (§13/§30) ─────────────────────
    legacy_route: Optional[str] = None
    legacy_tool: Optional[str] = None
    legacy_reason: Optional[str] = None
    legacy_subtype: Optional[str] = None
    match_route: Optional[bool] = None
    match_tool: Optional[bool] = None
    match_reason: Optional[bool] = None
    match_subtype: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route.value,
            "intent": self.intent,
            "subtype": self.subtype,
            "capability": self.capability.value if self.capability else None,
            "tool": self.tool,
            "policy": self.policy,
            "reason": self.reason,
            "confidence": self.confidence,
            "risk_class": self.risk_class,
            "rollout_mode": self.rollout_mode,
            "health_state": self.health_state,
            "policy_version": self.policy_version,
            "legacy_route": self.legacy_route,
            "legacy_tool": self.legacy_tool,
            "legacy_reason": self.legacy_reason,
            "legacy_subtype": self.legacy_subtype,
            "match_route": self.match_route,
            "match_tool": self.match_tool,
            "match_reason": self.match_reason,
            "match_subtype": self.match_subtype,
        }


@dataclass(frozen=True)
class PolicyDecision:
    """Sprint 1.3.1 §1 — the canonical policy result.

    Mandatory fields: route, reason_code, risk_class, capability, tool,
    rollout_mode, health_state, confidence, policy_version.

    ``route`` is the CapabilityRoute the caller must act on
    (V2 | LEGACY | DENY). ``reason_code`` is a canonical
    :class:`ReasonCode` (None only when ALLOW). ``evaluated_checks`` is
    the bounded §22 trace (check → outcome pairs; never raw user data).
    """

    route: CapabilityRoute
    reason_code: Optional[str]
    risk_class: RiskClass
    capability: Optional[str] = None
    tool: Optional[str] = None
    rollout_mode: str = "off"
    health_state: str = "UNKNOWN"
    confidence: Optional[float] = None
    policy_version: str = "cap-policy-v1"
    evaluated_checks: Tuple[Tuple[str, Any], ...] = ()

    @property
    def allowed(self) -> bool:
        return self.route is CapabilityRoute.V2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route.value,
            "reason_code": self.reason_code,
            "risk_class": self.risk_class.value,
            "capability": self.capability,
            "tool": self.tool,
            "rollout_mode": self.rollout_mode,
            "health_state": self.health_state,
            "confidence": self.confidence,
            "policy_version": self.policy_version,
            "evaluated_checks": [list(c) for c in self.evaluated_checks],
        }


__all__ = [
    "ReasonCode",
    "PolicyReason",
    "CapabilityRequirement",
    "CapabilityDescriptor",
    "ResolvedCapability",
    "CapabilityRouteDecision",
    "PolicyDecision",
]
