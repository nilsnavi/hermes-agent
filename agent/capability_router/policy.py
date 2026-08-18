"""Capability Policy Engine (Sprint 1.3.1 — CAPABILITY POLICY ENGINE
HARDENING; builds on 1.3.0 §8-§9, §25-§26).

``CapabilityPolicyEngine.evaluate(intent, requirement, descriptor,
context)`` returns a :class:`~agent.capability_router.models.PolicyDecision`:

    route=ALLOW_V2  → route V2 (verified capability, one tool)
    route=LEGACY    → route LEGACY (fail closed, reason_code set)
    route=DENY      → reserved; NEVER returned in 1.3.1 (§22 document-only)

Canonical precedence (Sprint 1.3.1 §3) — first terminal reason wins:

    1.  UNSAFE_INTENT
    2.  MIXED_UNSAFE_INTENT
    3.  SECRET_QUERY / FILESYSTEM_NOT_ALLOWED / WEB_NOT_ALLOWED
        (forbidden class)
    4.  CAPABILITY_UNSUPPORTED (unsupported capability)
    5.  CAPABILITY_UNVERIFIED / TOOL_UNVERIFIED (unverified
        capability/tool)
    6.  TOOL_RISK_MISMATCH (risk mismatch / effective risk)
    7.  NETWORK_NOT_ALLOWED
    8.  APPROVAL_REQUIRED
    9.  HEALTH_UNAVAILABLE (health gate)
    10. LOW_CONFIDENCE / AMBIGUOUS_INTENT
    11. ROLLOUT_DISABLED / ROLLOUT_LIMIT (rollout policy — evaluated
        last, after health/confidence, before ALLOW)
    12. ALLOW_V2

Effective risk (Sprint 1.3.1 §4) = max(intent_risk, capability_risk,
tool_risk, context_risk) — NEVER minimum (§25). A capability descriptor
can never lower the risk reported by intent classification; intent
safety cannot be downgraded by tool metadata (§26): intent WRITE +
tool READ_ONLY is still unsafe by intent; intent READ_ONLY + tool
WRITE is a mismatch → LEGACY/DENY.

Health gate (Sprint 1.3.1 §6/§7): the descriptor declares a
HealthRequirement (HEALTHY / DEGRADED_ALLOWED / NO_HEALTH_REQUIREMENT).
Unknown/unavailable health fails closed to LEGACY for the production
read surface (HEALTHY). Cached health carries a bounded TTL with a
monotonic timestamp — an expired snapshot is UNKNOWN (§7), never
stale-ok.

Fail closed (Sprint 1.3.1 §8): any exception, missing metadata, unknown
enum, invalid descriptor or unknown rollout mode → LEGACY (or DENY),
NEVER ALLOW. The engine is PURE (§18): deterministic, no network, no
DB, no side effects; exceptions injected into any resolver/parser are
swallowed to LEGACY (never ALLOW, §19).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agent.intent_router.enforcement import (
    SEARCH_ALLOWED_SOURCES,
    SEARCH_ALLOWED_SUBTYPES,
    has_mixed_unsafe_intent,
    search_prod_allowlist_matches,
    status_read_allowlist_matches,
)
from agent.operational_search.normalize import (
    is_secret_query,
    validate_query,
)

from .capabilities import (
    AccessMode,
    ApprovalPolicy,
    Capability,
    EXPECTED_SIDE_EFFECT_TO_RISK,
    HealthRequirement,
    HealthState,
    NetworkPolicy,
    PolicyVerdict,
    RiskClass,
    max_risk,
)
from .flags import parse_rollout_mode
from .models import CapabilityRequirement, PolicyDecision, ReasonCode
from .registry import RegistryEntry

#: Minimum confidence for a V2 route (mirrors the 1.2.x gate).
DEFAULT_MIN_CONFIDENCE = 0.7

#: Canonical policy version (Sprint 1.3.1 §10) — every decision carries
#: it; telemetry exposes it.
POLICY_VERSION = "cap-policy-v1"

#: ExpectedSideEffect values compatible with a read-only route.
_READ_ONLY_SIDE_EFFECTS = frozenset({"none", "read_only"})

#: IntentRisk values compatible with a read-only route.
_READ_ONLY_INTENT_RISKS = frozenset({"low"})

#: IntentRisk → RiskClass (for the §25 max()).
_INTENT_RISK_TO_CLASS: Dict[str, RiskClass] = {
    "low": RiskClass.READ_ONLY,
    "medium": RiskClass.REVERSIBLE_WRITE,
    "high": RiskClass.IRREVERSIBLE_WRITE,
    "critical": RiskClass.SYSTEM_CONTROL,
    "unknown": RiskClass.UNKNOWN,
}

#: Unsafe intent families (never routable, defensive gate #1).
_UNSAFE_INTENTS = frozenset({
    "write_action", "delete_action", "system_action",
    "schedule_action", "approval_action", "unknown",
})

#: Deny-list capability families (Sprint 1.3.1 §2 — forbidden class).
_FORBIDDEN_CAPABILITY_CLASS = {
    "FILESYSTEM_SEARCH": ReasonCode.FILESYSTEM_NOT_ALLOWED,
    "WEB_SEARCH": ReasonCode.WEB_NOT_ALLOWED,
    "SECRET_ACCESS": ReasonCode.SECRET_QUERY,
}

#: HealthState values → accepted by each HealthRequirement.
_HEALTH_REQ_ACCEPT: Dict[HealthRequirement, frozenset] = {
    HealthRequirement.HEALTHY: frozenset({HealthState.HEALTHY}),
    HealthRequirement.DEGRADED_ALLOWED: frozenset({
        HealthState.HEALTHY, HealthState.DEGRADED}),
    HealthRequirement.NO_HEALTH_REQUIREMENT: frozenset({
        HealthState.HEALTHY, HealthState.DEGRADED, HealthState.UNHEALTHY,
        HealthState.UNKNOWN}),
}

#: Default health TTL for a cached snapshot (seconds, §7).
DEFAULT_HEALTH_TTL = 30.0


def normalize_health_snapshot(health: Optional[Dict[str, Any]],
                              ttl: Optional[float] = None) -> HealthState:
    """§6/§7 — normalize a health snapshot to a HealthState.

    ``None`` or a dict without ``status`` → UNKNOWN. A snapshot with a
    monotonic ``fetched_at`` older than ``ttl`` seconds → UNKNOWN
    (expired health is never stale-ok, §7). Any other status value →
    UNKNOWN (unknown enum fails closed, §8).
    """
    if not health:
        return HealthState.UNKNOWN
    status = health.get("status")
    if status is None:
        return HealthState.UNKNOWN
    fetched_at = health.get("fetched_at")
    if fetched_at is not None and ttl is not None:
        import time
        try:
            age = time.monotonic() - float(fetched_at)
            if age > float(ttl):
                return HealthState.UNKNOWN
        except (TypeError, ValueError):
            return HealthState.UNKNOWN  # malformed timestamp → closed
    norm = {
        "healthy": HealthState.HEALTHY,
        "degraded": HealthState.DEGRADED,
        "unhealthy": HealthState.UNHEALTHY,
        "unknown": HealthState.UNKNOWN,
    }.get(str(status).strip().lower())
    return norm if norm is not None else HealthState.UNKNOWN


@dataclass
class PolicyContext:
    """Everything the policy engine needs about one request.

    ``text`` is the safe request text (never persisted); the engine
    derives allowlist/query/secret/mixed-intent facts from it with the
    verified legacy helpers. Health, confidence and the classification
    fields are passed by the caller.

    Sprint 1.3.1 additions: ``rollout_mode`` (normalized §9),
    ``context_risk`` (§4 — context risk grade, default READ_ONLY),
    ``health_ttl`` (§7 — bounded TTL for the cached snapshot).
    """

    text: str = ""
    health: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    intent_risk: Optional[str] = None        # IntentRisk value
    expected_side_effect: Optional[str] = None  # ExpectedSideEffect
    lexical_hits: List[str] = field(default_factory=list)
    subtype: Optional[str] = None
    # SEARCH_READ scope controls:
    search_mode: str = "off"                 # off|shadow|canary|limited_enforce
    live: bool = True
    success_live: int = 0
    max_success_live: int = 50
    # Sprint 1.3.1 — rollout normalization + context risk + health TTL:
    rollout_mode: Optional[str] = None     # normalized §9 (None → search_mode)
    context_risk: Optional[str] = None       # RiskClass value (§4)
    health_ttl: Optional[float] = None       # bounded TTL (§7)


class CapabilityPolicyEngine:
    """Fail-closed policy engine (§8-§9). PURE — never executes."""

    VERSION = POLICY_VERSION

    def __init__(
        self,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        require_health: bool = True,
        health_ttl: Optional[float] = DEFAULT_HEALTH_TTL,
    ) -> None:
        self.min_confidence = float(min_confidence)
        self.require_health = bool(require_health)
        self.health_ttl = health_ttl

    # ── evaluation ────────────────────────────────────────────────

    def evaluate(
        self,
        intent: str,
        requirement: CapabilityRequirement,
        descriptor: RegistryEntry,
        context: PolicyContext,
    ) -> PolicyDecision:
        """Return a :class:`PolicyDecision` (never raises; §19)."""
        try:
            return self._evaluate_unsafe(intent, requirement, descriptor,
                                         context)
        except Exception:  # §8/§19 — exceptions fail closed, never ALLOW
            return self._policy_error(context)

    def _evaluate_unsafe(
        self,
        intent: str,
        requirement: CapabilityRequirement,
        descriptor: RegistryEntry,
        context: PolicyContext,
    ) -> PolicyDecision:
        checks: List[Tuple[str, Any]] = []
        capability = requirement.capability.value
        tool = descriptor.tool_name
        rollout_mode = parse_rollout_mode(
            context.rollout_mode or context.search_mode)

        def _fail(reason: str) -> PolicyDecision:
            return self._fail(PolicyDecision, reason=reason,
                              context=context, descriptor=descriptor,
                              capability=capability, tool=tool,
                              checks=checks, rollout_mode=rollout_mode)

        # ── 1) unsafe intent — hard gate, defensive (§3 #1) ────────
        checks.append(("unsafe", intent in _UNSAFE_INTENTS))
        if intent in _UNSAFE_INTENTS:
            return _fail(ReasonCode.UNSAFE_INTENT)

        # ── 2) mixed unsafe intent — unsafe side first (§3 #2, §14) ─
        # Applied to the SEARCH surface only: the verified 1.2.3
        # contract scopes the substring unsafe-word detector to
        # SEARCH_READ (STATUS_READ's own risk/intent gates already
        # resolve the unsafe side first). The detector is substring-
        # based ("run" ⊂ "runtime") — applying it to status phrases
        # would false-block the production STATUS corpus.
        if intent == "search_read" and has_mixed_unsafe_intent(context.text):
            return _fail(ReasonCode.MIXED_UNSAFE_INTENT)

        # ── 3) forbidden class — secret/filesystem/web (§3 #3) ─────
        # SECRET_QUERY for the search surface; the deny-list capability
        # families (FILESYSTEM_SEARCH / WEB_SEARCH / SECRET_ACCESS)
        # fail closed here too — they are never routable (§22).
        if is_secret_query(context.text):
            return _fail(ReasonCode.SECRET_QUERY)
        forbidden = _FORBIDDEN_CAPABILITY_CLASS.get(capability)
        if forbidden is not None:
            return _fail(forbidden)
        checks.append(("forbidden_class", False))

        # ── 4) unsupported capability (§3 #4) — resolver-level, but
        #    defensive here: an unregistered capability is not routable.
        if not isinstance(requirement.capability, Capability):
            return _fail(ReasonCode.CAPABILITY_UNSUPPORTED)
        checks.append(("capability_supported", True))

        # ── 5) unverified capability/tool (§3 #5, §16/§17) ─────────
        # Tool metadata is authoritative for execution risk but cannot
        # reduce intent risk; missing/unknown metadata → TOOL_UNVERIFIED.
        if not descriptor.verified:
            return _fail(ReasonCode.CAPABILITY_UNVERIFIED)
        checks.append(("capability_verified", True))
        if not self._tool_contract_ok(descriptor):
            return _fail(ReasonCode.TOOL_UNVERIFIED)
        checks.append(("tool_verified", True))

        # ── 6) risk mismatch / effective risk (§3 #6, §4) ──────────
        # A KNOWN tool risk above READ_ONLY is a risk mismatch
        # (TOOL_RISK_MISMATCH) — not an unverified tool (§16: tool
        # metadata is authoritative for execution risk). Effective
        # risk = max(intent, capability, tool, context) — never min.
        if context.intent_risk not in _READ_ONLY_INTENT_RISKS:
            return _fail(ReasonCode.TOOL_RISK_MISMATCH)
        if context.expected_side_effect not in _READ_ONLY_SIDE_EFFECTS:
            return _fail(ReasonCode.TOOL_RISK_MISMATCH)
        effective = self._effective_risk(requirement, descriptor, context)
        if effective is not RiskClass.READ_ONLY:
            return _fail(ReasonCode.TOOL_RISK_MISMATCH)
        checks.append(("risk_ok", effective.value))

        # ── 7) network violation (§3 #7) ────────────────────────────
        if self._network_violation(requirement, descriptor):
            return _fail(ReasonCode.NETWORK_NOT_ALLOWED)
        checks.append(("network_ok", True))

        # ── 8) approval requirement (§3 #8) ─────────────────────────
        if self._approval_required(requirement, descriptor):
            return _fail(ReasonCode.APPROVAL_REQUIRED)
        checks.append(("approval_ok", True))

        # ── 9) health gate (§3 #9, §6) — unknown/unavailable fails
        #    closed for the production read surface; expired TTL → UNKNOWN.
        health_state = normalize_health_snapshot(
            context.health, ttl=self.health_ttl if self.require_health
            else None)
        if self.require_health:
            req = descriptor.health_requirement \
                if hasattr(descriptor, "health_requirement") \
                else HealthRequirement.HEALTHY
            if health_state not in _HEALTH_REQ_ACCEPT.get(req, frozenset()):
                return _fail(ReasonCode.HEALTH_UNAVAILABLE)
        checks.append(("health", health_state.value))

        # ── 10) confidence / ambiguity (§3 #10) ─────────────────────
        # NaN confidence must fail closed too: NaN < min is False, so
        # the comparison is inverted (not >= min) — invalid values
        # (None/NaN/negative) can never pass (§8 invalid confidence).
        if context.confidence is None or \
                not (context.confidence >= self.min_confidence):
            return _fail(ReasonCode.LOW_CONFIDENCE)
        if "ambiguous" in (context.lexical_hits or []):
            return _fail(ReasonCode.AMBIGUOUS_INTENT)
        checks.append(("confidence", context.confidence))

        # ── 11) rollout policy (§3 #11 — evaluated last) ────────────
        if intent == "search_read":
            # Search authority exists ONLY in limited_enforce (1.2.4).
            if rollout_mode != "limited_enforce":
                return _fail(ReasonCode.ROLLOUT_DISABLED)
            # Production sample cap — LIVE successes only (§11 1.2.4).
            if context.live and \
                    context.success_live >= context.max_success_live:
                return _fail(ReasonCode.ROLLOUT_LIMIT)
            checks.append(("rollout", rollout_mode))
        else:
            checks.append(("rollout", rollout_mode))

        # ── 12) capability-specific gates (verified 1.2.x contracts —
        #    placed AFTER rollout to preserve reason-code equivalence
        #    with the legacy 1.2.4 pipeline, which checked these last).
        if intent == "status_read":
            if not status_read_allowlist_matches(context.text):
                return _fail(ReasonCode.ALLOWLIST_MISS)
            checks.append(("allowlist", True))
        elif intent == "search_read":
            if not search_prod_allowlist_matches(context.text):
                return _fail(ReasonCode.ALLOWLIST_MISS)
            if context.subtype is None or \
                    context.subtype not in SEARCH_ALLOWED_SUBTYPES:
                return _fail(ReasonCode.SUBTYPE_NOT_ALLOWED)
            from agent.intent_router.enforcement import detect_search_source
            source = detect_search_source(context.text)
            if source is None or source not in SEARCH_ALLOWED_SOURCES:
                return _fail(ReasonCode.SOURCE_NOT_ALLOWED)
            query_ok, _ = validate_query(context.text)
            if not query_ok:
                return _fail(ReasonCode.QUERY_INVALID)
            checks.append(("search_gates", True))

        return PolicyDecision(
            route=_verdict_to_route(PolicyVerdict.ALLOW_V2),
            reason_code=None,
            risk_class=RiskClass.READ_ONLY,
            capability=capability,
            tool=tool,
            rollout_mode=rollout_mode,
            health_state=health_state.value,
            confidence=context.confidence,
            policy_version=self.VERSION,
            evaluated_checks=tuple(checks),
        )

    # ── helpers ───────────────────────────────────────────────────

    def _policy_error(self, context: PolicyContext) -> PolicyDecision:
        """§8/§19 — absolute fail-closed fallback. Never touches the
        descriptor or the health resolver (both may be the exception
        source) — only the safe context fields are read. Never ALLOW."""
        try:
            health_state = normalize_health_snapshot(context.health)
        except Exception:
            health_state = HealthState.UNKNOWN
        return PolicyDecision(
            route=_verdict_to_route(PolicyVerdict.LEGACY),
            reason_code=ReasonCode.POLICY_INTERNAL_ERROR,
            risk_class=RiskClass.UNKNOWN,
            capability=None,
            tool=None,
            rollout_mode=parse_rollout_mode(
                context.rollout_mode or context.search_mode),
            health_state=health_state.value,
            confidence=context.confidence,
            policy_version=self.VERSION,
            evaluated_checks=(("fail_closed", True),),
        )

    def _fail(self, _cls, *, reason: str, context: PolicyContext,
              descriptor: RegistryEntry, capability: Optional[str],
              tool: Optional[str], checks: Optional[List] = None,
              rollout_mode: str = "off") -> PolicyDecision:
        health_state = normalize_health_snapshot(
            context.health, ttl=self.health_ttl if self.require_health
            else None)
        return PolicyDecision(
            route=_verdict_to_route(PolicyVerdict.LEGACY),
            reason_code=reason,
            risk_class=self._effective_risk(
                CapabilityRequirement(
                    capability=descriptor.capability
                    if hasattr(descriptor, "capability") else
                    Capability.STATUS_RUNTIME),
                descriptor, context),
            capability=capability,
            tool=tool,
            rollout_mode=parse_rollout_mode(
                context.rollout_mode or context.search_mode),
            health_state=health_state.value,
            confidence=context.confidence,
            policy_version=self.VERSION,
            evaluated_checks=tuple(checks or ()),
        )

    def _effective_risk(
        self,
        requirement: CapabilityRequirement,
        descriptor: RegistryEntry,
        context: PolicyContext,
    ) -> RiskClass:
        """§4 — max(intent_risk, capability_risk, tool_risk,
        context_risk). Never min. Intent risk comes from the
        classifier's expected side effect (and is never downgraded by
        tool metadata, §26). Tool risk comes from the verified
        contract. Capability risk is the requirement's access mode.
        Context risk is the caller-supplied context grade (§4)."""
        intent_risk = EXPECTED_SIDE_EFFECT_TO_RISK.get(
            context.expected_side_effect or "unknown", RiskClass.UNKNOWN)
        tool_risk = _RISK_FROM_STRING.get(
            descriptor.side_effect, RiskClass.UNKNOWN)
        mode_risk = (RiskClass.READ_ONLY
                     if requirement.access_mode is AccessMode.READ_ONLY
                     else RiskClass.IRREVERSIBLE_WRITE)
        context_risk = _RISK_FROM_STRING.get(
            context.context_risk or "", RiskClass.UNKNOWN) \
            if context.context_risk else RiskClass.READ_ONLY
        return max_risk(intent_risk, tool_risk, mode_risk, context_risk)

    def _tool_contract_ok(self, descriptor: RegistryEntry) -> bool:
        """§3 #5 — verified tool with KNOWN, READ_ONLY-compatible +
        idempotent metadata. Unknown side_effect is NOT a verified
        contract — metadata that does not confirm read-only is
        TOOL_UNVERIFIED (§16: missing/unknown metadata → unverified).
        A KNOWN risk above READ_ONLY is not unverified — it is a risk
        mismatch judged by the §4 effective-risk max() in gate #6.
        Network has its OWN gate (§3 #7)."""
        return bool(
            descriptor.verified
            and descriptor.side_effect in _RISK_FROM_STRING
            and descriptor.side_effect != RiskClass.UNKNOWN.value
            and descriptor.idempotent
        )

    def _network_violation(
        self,
        requirement: CapabilityRequirement,
        descriptor: RegistryEntry,
    ) -> bool:
        """§3 #7 — requirement forbids network but the tool uses it."""
        return (
            requirement.network_policy is NetworkPolicy.LOCAL_ONLY
            and bool(descriptor.network)
        )

    def _approval_required(
        self,
        requirement: CapabilityRequirement,
        descriptor: RegistryEntry,
    ) -> bool:
        """§3 #8 — either side demands approval."""
        return (
            requirement.approval_policy is ApprovalPolicy.REQUIRED
            or bool(descriptor.approval_required)
        )


def _verdict_to_route(verdict: PolicyVerdict):
    """PolicyVerdict → CapabilityRoute (import-time-safe mapping)."""
    from .capabilities import CapabilityRoute
    return {
        PolicyVerdict.ALLOW_V2: CapabilityRoute.V2,
        PolicyVerdict.DENY: CapabilityRoute.DENY,
        PolicyVerdict.LEGACY: CapabilityRoute.LEGACY,
    }[verdict]


#: RiskClass values → RiskClass (string forms from the contract).
_RISK_FROM_STRING: Dict[str, RiskClass] = {
    RiskClass.READ_ONLY.value: RiskClass.READ_ONLY,
    RiskClass.REVERSIBLE_WRITE.value: RiskClass.REVERSIBLE_WRITE,
    RiskClass.IRREVERSIBLE_WRITE.value: RiskClass.IRREVERSIBLE_WRITE,
    RiskClass.SYSTEM_CONTROL.value: RiskClass.SYSTEM_CONTROL,
    RiskClass.SECRET_ACCESS.value: RiskClass.SECRET_ACCESS,
    RiskClass.UNKNOWN.value: RiskClass.UNKNOWN,
}


__all__ = [
    "CapabilityPolicyEngine",
    "PolicyContext",
    "DEFAULT_MIN_CONFIDENCE",
    "DEFAULT_HEALTH_TTL",
    "POLICY_VERSION",
    "normalize_health_snapshot",
]
