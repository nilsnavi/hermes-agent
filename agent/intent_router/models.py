"""Intent Router data model (Sprint 1.1) — classification DTOs.

Sprint 1.1 is OBSERVE / RECOMMEND ONLY. Nothing in this module can
execute, switch, send or call a tool: it is a pure data model for
classification, scoring and routing RECOMMENDATION.

Design rules:

- Intent is NOT risk. Both are carried separately.
- ExpectedSideEffect is the classifier's EXPECTATION, kept distinct
  from ToolMetadata.SideEffectClass (the actual registry fact) — but
  the values are compatible (read_only / reversible_write / ...).
- candidate_route vs effective_route are SEPARATE fields: the router
  may see a request as V2_CANARY-capable (candidate) while the
  effective route stays LEGACY because of a gate (health, kill
  switch, allowlist, mode).
- No raw prompt / authorization / tool args / full metadata ever
  enter a decision object.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── enums ────────────────────────────────────────────────────────────


class IntentType(Enum):
    """Intent taxonomy (§8) — coarse, not hundreds of types."""

    CONVERSATION = "conversation"
    SUMMARIZATION = "summarization"
    INFORMATION_READ = "information_read"
    STATUS_READ = "status_read"
    SEARCH_READ = "search_read"
    ANALYSIS = "analysis"
    PLANNING = "planning"
    CODE_ASSIST = "code_assist"
    DIAGNOSTIC = "diagnostic"
    APPROVAL_ACTION = "approval_action"
    WRITE_ACTION = "write_action"
    DELETE_ACTION = "delete_action"
    SYSTEM_ACTION = "system_action"
    SCHEDULE_ACTION = "schedule_action"
    UNKNOWN = "unknown"


class IntentRisk(Enum):
    """Risk of the intent (§9) — separate from intent type."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ExpectedSideEffect(Enum):
    """Classifier's side-effect expectation (§10).

    Values are compatible with ToolMetadata.SideEffectClass so mappings
    are straightforward, but this is an EXPECTATION, not the registry
    fact.
    """

    NONE = "none"
    READ_ONLY = "read_only"
    REVERSIBLE_WRITE = "reversible_write"
    IRREVERSIBLE_WRITE = "irreversible_write"
    SYSTEM_CHANGE = "system_change"
    UNKNOWN = "unknown"


class RoutingRecommendation(Enum):
    """Recommended route (§11). Sprint 1.1 uses it as recommendation only."""

    LEGACY = "legacy"
    V2_SHADOW = "v2_shadow"
    V2_CANARY = "v2_canary"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"
    UNKNOWN = "unknown"


class RouterMode(Enum):
    """Router modes (§36). Sprint 1.1: OFF and OBSERVE only.

    SHADOW_DECISION / ENFORCE are NOT implemented in production
    (Sprint 1.1.1 §6): parsing them fails closed to OFF.
    """

    OFF = "off"
    OBSERVE = "observe"
    SHADOW_DECISION = "shadow_decision"
    ENFORCE = "enforce"


class SampleSource(Enum):
    """Observation sample provenance (Sprint 1.1.1 §10) — metrics must
    keep the four classes separate and never fake LIVE traffic."""

    LIVE = "LIVE"
    INTERNAL_SYNTHETIC = "INTERNAL_SYNTHETIC"
    EXPLICIT_CANARY = "EXPLICIT_CANARY"
    EXPLICIT_SHADOW = "EXPLICIT_SHADOW"


class ActualRoute(Enum):
    """Actual production route the gateway took (Sprint 1.1.1 §11).

    Exact values from the brief. Never inferred from response text —
    always derived from the routing state/code path (V2Decision)."""

    LEGACY = "LEGACY"
    V2_CANARY = "V2_CANARY"
    SHADOW = "SHADOW"
    OPERATIONS = "OPERATIONS"
    OTHER = "OTHER"


class ReasonCode(Enum):
    """Structured reason codes (§14) — never bare free text."""

    READ_ONLY_INTENT = "read_only_intent"
    WRITE_INTENT = "write_intent"
    UNKNOWN_INTENT = "unknown_intent"
    CRITICAL_RISK = "critical_risk"
    CAPABILITY_MISSING = "capability_missing"
    CANARY_ALLOWLIST_REQUIRED = "canary_allowlist_required"
    TOOL_NOT_AVAILABLE = "tool_not_available"
    APPROVAL_REQUIRED = "approval_required"
    LEGACY_ONLY_POLICY = "legacy_only_policy"
    LOW_CONFIDENCE = "low_confidence"
    UNSAFE_SIDE_EFFECT = "unsafe_side_effect"
    ROUTER_ERROR = "router_error"
    # gate reasons (extension of the brief's list, still structured)
    HEALTH_GATE = "health_gate"
    CANARY_DISABLED = "canary_disabled"
    SHADOW_DISABLED = "shadow_disabled"
    MODE_OFF = "mode_off"
    SCHEDULE_LEGACY = "schedule_legacy"
    SYSTEM_LEGACY = "system_legacy"
    APPROVAL_OPS_PATH = "approval_ops_path"
    DENY_BY_POLICY = "deny_by_policy"


class MismatchClass(Enum):
    """Routing comparison classes (§44)."""

    ROUTER_V2_ACTUAL_LEGACY = "router_v2_actual_legacy"
    ROUTER_LEGACY_ACTUAL_CANARY = "router_legacy_actual_canary"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    RISK_CONFLICT = "risk_conflict"
    POLICY_CONFLICT = "policy_conflict"
    HEALTH_GATE = "health_gate"
    ALLOWLIST_GATE = "allowlist_gate"
    NO_MISMATCH = "no_mismatch"


#: Confidence buckets (§52) — calibration without fake precision.
CONFIDENCE_BUCKETS = (
    (0.0, 0.5),
    (0.5, 0.7),
    (0.7, 0.9),
    (0.9, 1.0),
)


def confidence_bucket(confidence: Optional[float]) -> Optional[str]:
    if confidence is None:
        return None
    for lo, hi in CONFIDENCE_BUCKETS:
        if lo <= confidence < hi:
            return f"{lo:.1f}-{hi:.1f}"
    if confidence == 1.0:
        return "0.9-1.0"
    return None


# ── input features (§17) ─────────────────────────────────────────────


@dataclass(frozen=True)
class RequestIntentFeatures:
    """Safe normalized representation of an incoming request.

    NEVER carries the full prompt body. ``lexical_hits`` is a small
    ordered list of matched keyword family names (e.g. ``status``,
    ``delete``) — never the matched text itself.
    """

    request_id: str = ""
    request_type: Optional[str] = None
    command: Optional[str] = None
    channel: Optional[str] = None
    has_attachment: bool = False
    explicit_v2_flag: Optional[str] = None  # "canary" | "shadow" | None
    declared_action: Optional[str] = None
    lexical_hits: List[str] = field(default_factory=list)
    token_bucket: Optional[str] = None  # "tiny" | "short" | "medium" | "long"
    internal: bool = False  # explicit internal allowlist marker

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "request_type": self.request_type,
            "command": self.command,
            "channel": self.channel,
            "has_attachment": self.has_attachment,
            "explicit_v2_flag": self.explicit_v2_flag,
            "declared_action": self.declared_action,
            "lexical_hits": list(self.lexical_hits),
            "token_bucket": self.token_bucket,
            "internal": self.internal,
        }


# ── routing decision (§12) ───────────────────────────────────────────


@dataclass
class IntentRoutingDecision:
    """One routing decision. No raw payload persisted."""

    request_id: str
    intent: str
    risk: str
    expected_side_effect: str
    recommended_route: str
    candidate_route: str
    effective_route: str
    confidence: Optional[float]
    reason_codes: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    eligible_tools: List[str] = field(default_factory=list)
    approval_required: bool = False
    canary_eligible: bool = False
    shadow_eligible: bool = False
    fallback_route: str = "legacy"
    classifier_version: str = ""
    policy_version: str = ""
    timestamp: Optional[str] = None
    duration_ms: Optional[float] = None
    # Sprint 1.1.1 observe-calibration fields (§9): actual route the
    # gateway took (never inferred from response text), sample
    # provenance, recommendation-vs-actual match, missing capabilities.
    actual_route: Optional[str] = None
    sample_source: str = "LIVE"
    matched: Optional[bool] = None
    missing_capabilities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "intent": self.intent,
            "risk": self.risk,
            "expected_side_effect": self.expected_side_effect,
            "recommended_route": self.recommended_route,
            "candidate_route": self.candidate_route,
            "effective_route": self.effective_route,
            "confidence": self.confidence,
            "confidence_bucket": confidence_bucket(self.confidence),
            "reason_codes": list(self.reason_codes),
            "required_capabilities": list(self.required_capabilities),
            "eligible_tools": list(self.eligible_tools),
            "approval_required": self.approval_required,
            "canary_eligible": self.canary_eligible,
            "shadow_eligible": self.shadow_eligible,
            "fallback_route": self.fallback_route,
            "classifier_version": self.classifier_version,
            "policy_version": self.policy_version,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "actual_route": self.actual_route,
            "sample_source": self.sample_source,
            "matched": self.matched,
            "missing_capabilities": list(self.missing_capabilities),
        }


@dataclass
class RoutingComparison:
    """Recommended vs actual route (§42-44). No user content."""

    request_id: str
    recommended: str
    actual: str
    matched: bool
    mismatch_class: str
    actual_success: Optional[bool] = None
    actual_stop_reason: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "recommended": self.recommended,
            "actual": self.actual,
            "matched": self.matched,
            "mismatch_class": self.mismatch_class,
            "actual_success": self.actual_success,
            "actual_stop_reason": self.actual_stop_reason,
            "reason": self.reason,
        }


# ── router status (§72) ──────────────────────────────────────────────


@dataclass
class RouterStatus:
    enabled: bool
    mode: str
    router_version: str
    policy_version: str
    rules: int
    decision_count: int
    error_count: int
    unsafe_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "router_version": self.router_version,
            "policy_version": self.policy_version,
            "rules": self.rules,
            "decision_count": self.decision_count,
            "error_count": self.error_count,
            "unsafe_count": self.unsafe_count,
        }


__all__ = [
    "IntentType",
    "IntentRisk",
    "ExpectedSideEffect",
    "RoutingRecommendation",
    "RouterMode",
    "SampleSource",
    "ActualRoute",
    "ReasonCode",
    "MismatchClass",
    "CONFIDENCE_BUCKETS",
    "confidence_bucket",
    "RequestIntentFeatures",
    "IntentRoutingDecision",
    "RoutingComparison",
    "RouterStatus",
]
