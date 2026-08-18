"""Capability Router orchestration (Sprint 1.3.0 §1, §10, §13 +
Sprint 1.3.1 — canonical policy decisions).

``CapabilityRouter.decide(...)`` is the single routing pipeline:

    resolver → registry → policy → CapabilityRouteDecision

It takes the same inputs the legacy (1.2.4) enforcement used, computes
the capability decision deterministically, and — when a legacy outcome
is available — attaches shadow-comparison evidence (§13: route, tool,
reason, subtype match). The router NEVER executes tools: the gateway's
existing V2 canary path (Execution Adapter) consumes the outcome.

Modes (§15): off (inert — the IntentRouter must not call decide),
shadow (compare only), enforce (decide for the exact 1.2.4 scope:
STATUS_READ + SEARCH_READ limited production allowlist).

Sprint 1.3.1: the policy returns a canonical :class:`PolicyDecision`
(§1) with the canonical reason taxonomy (§2); the route decision now
carries risk_class / rollout_mode / health_state / policy_version
(§1 mandatory fields) and the §20 policy metrics are recorded.
Reason mapping: canonical ReasonCode → the legacy 1.2.4 block/deny
code, so §30 comparison metrics compare like-for-like.
"""

import time
from typing import Any, Dict, Optional

from .capabilities import CapabilityRoute
from .flags import parse_capability_router_mode, parse_rollout_mode
from .metrics import CapabilityRouterStats
from .models import (
    CapabilityRouteDecision,
    PolicyDecision,
    ReasonCode,
    ResolvedCapability,
)
from .policy import CapabilityPolicyEngine, POLICY_VERSION, PolicyContext
from .registry import CapabilityRegistry, RegistryEntry
from .resolver import CapabilityResolver

CAPABILITY_ROUTER_VERSION = "capability-router-v1"

#: Off-scope intents (any intent outside STATUS_READ/SEARCH_READ) get
#: the legacy INTENT_NOT_ALLOWED code from the 1.2.4 pipeline.
_OFF_SCOPE_INTENTS = frozenset({
    "conversation", "summarization", "information_read", "analysis",
    "planning", "code_assist", "diagnostic", "approval_action",
    "write_action", "delete_action", "system_action",
    "schedule_action", "unknown",
})

#: Canonical ReasonCode → legacy block/deny code, per family.
_LEGACY_REASON_BY_FAMILY: Dict[str, Dict[str, Optional[str]]] = {
    "status": {
        ReasonCode.UNSAFE_INTENT: "INTENT_NOT_ALLOWED",
        ReasonCode.MIXED_UNSAFE_INTENT: "UNSAFE_MIXED_INTENT",
        ReasonCode.CAPABILITY_UNSUPPORTED: "CAPABILITY",
        ReasonCode.CAPABILITY_UNVERIFIED: "TOOL_METADATA",
        ReasonCode.TOOL_UNVERIFIED: "TOOL_METADATA",
        ReasonCode.TOOL_RISK_MISMATCH: "POLICY",
        ReasonCode.NETWORK_NOT_ALLOWED: "POLICY",
        ReasonCode.APPROVAL_REQUIRED: "APPROVAL",
        ReasonCode.HEALTH_UNAVAILABLE: "HEALTH",
        ReasonCode.LOW_CONFIDENCE: "LOW_CONFIDENCE",
        ReasonCode.AMBIGUOUS_INTENT: "AMBIGUOUS",
        ReasonCode.ROLLOUT_DISABLED: "POLICY_DISABLED",
        ReasonCode.SOURCE_NOT_ALLOWED: "SOURCE_NOT_ALLOWED",
        ReasonCode.SECRET_QUERY: "SECRET_QUERY",
        ReasonCode.FILESYSTEM_NOT_ALLOWED: "POLICY",
        ReasonCode.WEB_NOT_ALLOWED: "POLICY",
        ReasonCode.POLICY_INTERNAL_ERROR: "POLICY",
        ReasonCode.ALLOWLIST_MISS: "ALLOWLIST",
        ReasonCode.SUBTYPE_NOT_ALLOWED: "POLICY",
        ReasonCode.QUERY_INVALID: "POLICY",
        ReasonCode.ROLLOUT_LIMIT: "POLICY_DISABLED",
    },
    "search": {
        ReasonCode.UNSAFE_INTENT: "INTENT_NOT_ALLOWED",
        ReasonCode.MIXED_UNSAFE_INTENT: "UNSAFE_MIXED_INTENT",
        ReasonCode.CAPABILITY_UNSUPPORTED: "CAPABILITY_MISSING",
        ReasonCode.CAPABILITY_UNVERIFIED: "TOOL_NOT_VERIFIED",
        ReasonCode.TOOL_UNVERIFIED: "TOOL_NOT_VERIFIED",
        ReasonCode.TOOL_RISK_MISMATCH: "POLICY",
        ReasonCode.NETWORK_NOT_ALLOWED: "POLICY",
        ReasonCode.APPROVAL_REQUIRED: "APPROVAL",
        ReasonCode.HEALTH_UNAVAILABLE: "HEALTH_UNAVAILABLE",
        ReasonCode.LOW_CONFIDENCE: "LOW_CONFIDENCE",
        ReasonCode.AMBIGUOUS_INTENT: "AMBIGUOUS",
        ReasonCode.ROLLOUT_DISABLED: "POLICY_DISABLED",
        ReasonCode.SOURCE_NOT_ALLOWED: "SOURCE_NOT_ALLOWED",
        ReasonCode.SECRET_QUERY: "SECRET_QUERY",
        ReasonCode.FILESYSTEM_NOT_ALLOWED: "POLICY",
        ReasonCode.WEB_NOT_ALLOWED: "POLICY",
        ReasonCode.POLICY_INTERNAL_ERROR: "POLICY",
        ReasonCode.ALLOWLIST_MISS: "SEARCH_NOT_ALLOWLISTED",
        ReasonCode.SUBTYPE_NOT_ALLOWED: "SEARCH_NOT_ALLOWLISTED",
        ReasonCode.QUERY_INVALID: "QUERY_INVALID",
        ReasonCode.ROLLOUT_LIMIT: "SEARCH_LIMIT_REACHED",
    },
}


def _enum_value(value: Any) -> Any:
    """Normalize an Enum to its value (classifier fields are Enums)."""
    if value is None:
        return None
    return getattr(value, "value", value)


def legacy_reason_for(
    policy_reason: Optional[str],
    intent: str,
) -> Optional[str]:
    """Map a canonical ReasonCode to the legacy 1.2.4 block/deny code.

    ``None`` (allowed) maps to None. Off-scope intents map every
    denial to INTENT_NOT_ALLOWED (the EnforcementPolicy's verdict for
    anything outside the enforced scope). Unknown reasons fail closed
    to the raw value (never silently equal).
    """
    if policy_reason is None:
        return None
    if intent not in ("status_read", "search_read"):
        return "INTENT_NOT_ALLOWED"
    family = "search" if intent == "search_read" else "status"
    return _LEGACY_REASON_BY_FAMILY[family].get(policy_reason,
                                                policy_reason)


class CapabilityRouter:
    """Resolve → registry → policy → decision (Sprint 1.3.0 §1)."""

    VERSION = CAPABILITY_ROUTER_VERSION

    def __init__(
        self,
        resolver: Optional[CapabilityResolver] = None,
        registry: Optional[CapabilityRegistry] = None,
        policy: Optional[CapabilityPolicyEngine] = None,
        mode: str = "off",
        clock=None,
    ) -> None:
        self._resolver = resolver or CapabilityResolver()
        self._registry = registry or CapabilityRegistry()
        self._policy = policy or CapabilityPolicyEngine()
        self.mode = parse_capability_router_mode(mode)
        self._clock = clock or (lambda: time.time())
        self.stats = CapabilityRouterStats()

    # ── registry / policy surface (tests + introspection) ─────────

    @property
    def registry(self) -> CapabilityRegistry:
        return self._registry

    @property
    def policy(self) -> CapabilityPolicyEngine:
        return self._policy

    @property
    def resolver(self) -> CapabilityResolver:
        return self._resolver

    # ── core decision (§1/§10) ────────────────────────────────────

    def decide(
        self,
        *,
        intent: str,
        subtype: Optional[str],
        text: str,
        classification: Any,
        health: Dict[str, Any],
        sample_source: str,
        search_mode: str,
        live: bool = True,
        success_live: int = 0,
        max_success_live: int = 50,
        legacy_outcome: Any = None,
    ) -> CapabilityRouteDecision:
        """One capability routing decision (deterministic, no LLM).

        ``classification`` is the classifier's Classification (risk,
        expected_side_effect, lexical_hits, confidence are read off
        it); ``legacy_outcome`` is the optional 1.2.4 EnforcementOutcome
        for shadow comparison (§13). Never raises into the caller on
        its own path — the IntentRouter wraps the call fail-closed.
        """
        started = self._clock()
        # 1) resolve (§7) — NO_CAPABILITY → LEGACY.
        resolved = self._resolve(intent, subtype)
        if resolved is None:
            return self._finish(
                intent=intent, subtype=subtype, text=text,
                classification=classification, resolved=None,
                route=CapabilityRoute.LEGACY,
                reason=ReasonCode.CAPABILITY_UNSUPPORTED,
                started=started, legacy_outcome=legacy_outcome,
            )
        # 2) registry (§4) — descriptor must exist (static surface).
        descriptor = self._registry.lookup(
            resolved.requirement.capability)
        if descriptor is None:
            return self._finish(
                intent=intent, subtype=subtype, text=text,
                classification=classification, resolved=resolved,
                route=CapabilityRoute.LEGACY,
                reason=ReasonCode.CAPABILITY_UNSUPPORTED,
                started=started, legacy_outcome=legacy_outcome,
            )
        # 3) policy (§8-§9 / 1.3.1 §3) — canonical PolicyDecision.
        context = PolicyContext(
            text=text or "",
            health=health or {},
            confidence=getattr(classification, "confidence", None),
            intent_risk=_enum_value(
                getattr(classification, "risk", None)),
            expected_side_effect=_enum_value(
                getattr(classification, "expected_side_effect", None)),
            lexical_hits=list(getattr(classification, "lexical_hits", [])
                              or []),
            subtype=subtype,
            search_mode=search_mode,
            live=live,
            success_live=int(success_live),
            max_success_live=int(max_success_live),
            rollout_mode=parse_rollout_mode(search_mode),
        )
        decision: PolicyDecision = self._policy.evaluate(
            intent, resolved.requirement, descriptor, context)
        route = decision.route
        reason = decision.reason_code
        return self._finish(
            intent=intent, subtype=subtype, text=text,
            classification=classification, resolved=resolved,
            route=route, reason=reason, started=started,
            legacy_outcome=legacy_outcome, policy_decision=decision,
        )

    # ── helpers ───────────────────────────────────────────────────

    def _resolve(
        self, intent: str, subtype: Optional[str],
    ) -> Optional[ResolvedCapability]:
        try:
            return self._resolver.resolve(intent, subtype)
        except Exception:
            return None  # deterministic resolver must never break the router

    def _finish(
        self, *, intent: str, subtype: Optional[str], text: str,
        classification: Any, resolved: Optional[ResolvedCapability],
        route: CapabilityRoute, reason: Optional[str], started: float,
        legacy_outcome: Any,
        policy_decision: Optional[PolicyDecision] = None,
    ) -> CapabilityRouteDecision:
        tool = resolved.tool if resolved is not None else None
        capability = (
            resolved.requirement.capability.value
            if resolved is not None else None)
        decision = CapabilityRouteDecision(
            route=route,
            intent=intent,
            subtype=subtype,
            capability=(
                resolved.requirement.capability if resolved is not None
                else None),
            tool=tool,
            policy=self._policy.VERSION,
            reason=reason,
            confidence=getattr(classification, "confidence", None),
            # Sprint 1.3.1 §1 — canonical decision fields.
            risk_class=(
                policy_decision.risk_class.value
                if policy_decision is not None else None),
            rollout_mode=(
                policy_decision.rollout_mode
                if policy_decision is not None else "off"),
            health_state=(
                policy_decision.health_state
                if policy_decision is not None else "UNKNOWN"),
            policy_version=(
                policy_decision.policy_version
                if policy_decision is not None else POLICY_VERSION),
        )
        duration_ms = round((self._clock() - started) * 1000.0, 3)
        # ── shadow comparison evidence (§13) ──────────────────────
        legacy_route = legacy_tool = legacy_reason = legacy_subtype = None
        if legacy_outcome is not None:
            allowed = bool(getattr(legacy_outcome, "allowed", False))
            legacy_route = "V2" if allowed else "LEGACY"
            tools = getattr(legacy_outcome, "eligible_tools", None) or []
            legacy_tool = tools[0] if tools else None
            legacy_reason = getattr(legacy_outcome, "block_reason", None)
            legacy_subtype = (
                getattr(legacy_outcome, "search_subtype", None)
                if intent == "search_read"
                else getattr(legacy_outcome, "status_subtype", None))
            decision.legacy_route = legacy_route
            decision.legacy_tool = legacy_tool
            decision.legacy_reason = legacy_reason
            decision.legacy_subtype = legacy_subtype
            decision.match_route = route.value == legacy_route
            # Tool comparison: a blocked route has NO tool to execute
            # (legacy eligible_tools=[] on deny); compare only the
            # V2-granted tool. Canary mode (V2_CANARY legacy) is out
            # of the capability-router scope → tool mismatch expected.
            decision.match_tool = (
                (tool if route is CapabilityRoute.V2 else None)
                == legacy_tool)
            decision.match_reason = (
                legacy_reason_for(reason, intent) == legacy_reason)
            decision.match_subtype = (subtype == legacy_subtype)
        self.stats.record(
            route=route.value,
            intent=intent,
            capability=capability,
            tool=tool,
            reason=reason,
            duration_ms=duration_ms,
            has_legacy=legacy_outcome is not None,
            decision_match=decision.match_route,
            tool_match=decision.match_tool,
            reason_match=decision.match_reason,
            subtype_match=decision.match_subtype,
            fail_closed=(
                reason == ReasonCode.POLICY_INTERNAL_ERROR
                if reason else False),
            policy_version=(
                policy_decision.policy_version
                if policy_decision is not None else POLICY_VERSION),
        )
        return decision


def benchmark_resolutions(n: int = 10000) -> Dict[str, float]:
    """§30/§31 — deterministic resolution benchmark (10,000 runs).

    Resolver-only path (resolve() per call) must be well under 1 ms
    p95; the full router decision under 5 ms p95. Sprint 1.3.1 adds a
    policy-only evaluation benchmark (p95 < 1 ms, §30).
    """
    import statistics

    router = CapabilityRouter()
    # resolver-only timings
    r_times: list = []
    for _ in range(n):
        t0 = time.perf_counter()
        router.resolver.resolve(
            "status_read", "gateway_status")
        r_times.append((time.perf_counter() - t0) * 1000.0)
    # policy-only timings (§30 — p95 < 1 ms)
    from agent.intent_router.classifier import RuleBasedIntentClassifier
    from agent.intent_router.evaluation import features_from_text

    classifier = RuleBasedIntentClassifier()
    classification = classifier.classify(
        features_from_text("статус gateway", request_id="bench"))
    resolved = router.resolver.resolve("status_read", "gateway_status")
    descriptor = router.registry.lookup(
        resolved.requirement.capability)
    p_times: list = []
    for _ in range(n):
        ctx = PolicyContext(
            text="статус gateway",
            health={"status": "healthy"},
            confidence=classification.confidence,
            intent_risk=getattr(classification.risk, "value", None),
            expected_side_effect=getattr(
                classification.expected_side_effect, "value", None),
            search_mode="off",
            rollout_mode="off",
        )
        t0 = time.perf_counter()
        router.policy.evaluate(
            "status_read", resolved.requirement, descriptor, ctx)
        p_times.append((time.perf_counter() - t0) * 1000.0)
    # full router timings (healthy, allowlisted status request)
    f_times: list = []
    for _ in range(n):
        t0 = time.perf_counter()
        router.decide(
            intent="status_read", subtype="gateway_status",
            text="статус gateway",
            classification=classification,
            health={"status": "healthy"},
            sample_source="INTERNAL_SYNTHETIC",
            search_mode="off",
        )
        f_times.append((time.perf_counter() - t0) * 1000.0)

    def _pct(xs: list, p: float) -> float:
        s = sorted(xs)
        return round(s[min(len(s) - 1, int(p / 100 * (len(s) - 1)))], 4)

    return {
        "resolver": {"p50_ms": _pct(r_times, 50),
                     "p95_ms": _pct(r_times, 95),
                     "mean_ms": round(statistics.mean(r_times), 4)},
        "policy": {"p50_ms": _pct(p_times, 50),
                   "p95_ms": _pct(p_times, 95),
                   "mean_ms": round(statistics.mean(p_times), 4)},
        "router": {"p50_ms": _pct(f_times, 50),
                   "p95_ms": _pct(f_times, 95),
                   "mean_ms": round(statistics.mean(f_times), 4)},
        "n": n,
    }


__all__ = [
    "CapabilityRouter",
    "legacy_reason_for",
    "benchmark_resolutions",
    "CAPABILITY_ROUTER_VERSION",
]
