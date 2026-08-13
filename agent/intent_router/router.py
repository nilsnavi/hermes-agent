"""Intent Router facade (Sprint 1.1 §36-43, §56-59) — OBSERVE ONLY.

``IntentRouter.observe(features)`` is the single production entry point:

1. classify (deterministic, no LLM),
2. capability match,
3. policy decide (candidate + effective routes),
4. explain + score,
5. emit a whitelisted event (in-memory bounded ring by default).

The router has ZERO execution authority: it never calls the
RuntimeOrchestrator, never switches routes, never sends anything. The
gateway adapter's existing deny-by-default decision remains the only
authority. Any exception inside the router fails closed to LEGACY with
ROUTER_ERROR (§20) — the request is never broken or mis-routed.

Observe mode adds negligible latency (deterministic, sub-ms); the
decision event is appended to an in-memory bounded ring (default 1000)
and optionally passed to a caller-supplied sink. NO row is written to
state.db per ordinary request (§41).
"""

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .capabilities import CapabilityRegistry
from .classifier import (
    Classification,
    IntentClassifier,
    RuleBasedIntentClassifier,
)
from .events import (
    INTENT_ROUTER_ERROR,
    INTENT_ROUTER_EVALUATED,
    router_error_payload,
    router_event_payload,
)
from .exceptions import IntentRouterError, RouterConfigurationError
from .models import (
    ActualRoute,
    ExpectedSideEffect,
    IntentRoutingDecision,
    IntentType,
    RequestIntentFeatures,
    RouterMode,
    RouterStatus,
    SampleSource,
)
from .policy import RouterPolicy
from .rules import RULES, RULES_VERSION

ROUTER_VERSION = "intent-router-v1"

# ActualRoute (Sprint 1.1.1 §11) → effective-route bucket for matching.
_ACTUAL_TO_EFFECTIVE = {
    "LEGACY": "legacy",
    "V2_CANARY": "v2_canary",
    "SHADOW": "v2_shadow",
    "OPERATIONS": "legacy",  # operations requests run the legacy pipeline
}

# recommended_route bucket → §12 metric name.
_REC_TO_METRIC = {
    "legacy": "legacy",
    "v2_shadow": "shadow",
    "v2_canary": "canary",
    "require_approval": "approval",
    "deny": "deny",
    "unknown": "unknown",
}


def _match_actual(effective_route: str,
                  actual_route: Optional[str]) -> Optional[bool]:
    """Recommendation-vs-actual match (§27): None when actual is unknown
    or unmappable; POLICY_MISMATCH vs CLASSIFICATION_ERROR are separated
    downstream (mismatch counters here are policy-level only)."""
    if not actual_route:
        return None
    eff = _ACTUAL_TO_EFFECTIVE.get(str(actual_route).upper())
    if eff is None:
        return None
    return eff == effective_route


def _rec_bucket(recommended_route: str) -> str:
    return _REC_TO_METRIC.get(str(recommended_route), "unknown")


def _act_bucket(actual_route: str) -> str:
    key = str(actual_route).upper()
    return {
        "LEGACY": "legacy",
        "V2_CANARY": "canary",
        "SHADOW": "shadow",
        "OPERATIONS": "operations",
        "OTHER": "other",
    }.get(key, "other")

_ROUTER_ENABLED_ENV = "HERMES_INTENT_ROUTER_ENABLED"
_ROUTER_MODE_ENV = "HERMES_INTENT_ROUTER_MODE"

_MODE_MAP = {
    "off": RouterMode.OFF,
    "observe": RouterMode.OBSERVE,
    "shadow_decision": RouterMode.SHADOW_DECISION,
    "enforce": RouterMode.ENFORCE,
}


def parse_mode(value: Optional[str]) -> RouterMode:
    """Strict mode parse. None/garbage → OFF (fail closed).

    ENFORCE and SHADOW_DECISION are NOT implemented in production
    (Sprint 1.1 §36 / 1.1.1 §6) — parsing them fails closed to OFF
    instead of constructing an unusable mode.
    """
    if value is None:
        return RouterMode.OFF
    mode = _MODE_MAP.get(str(value).strip().lower())
    if mode in (RouterMode.ENFORCE, RouterMode.SHADOW_DECISION):
        return RouterMode.OFF  # not implemented → fail closed
    return mode or RouterMode.OFF


def read_router_flags(
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Router feature flags (§37-38). Defaults: enabled=false, mode=off."""
    env = environ if environ is not None else os.environ
    enabled_raw = env.get(_ROUTER_ENABLED_ENV, "false")
    enabled = str(enabled_raw).strip().lower() in ("true", "1", "yes")
    mode = parse_mode(env.get(_ROUTER_MODE_ENV))
    return {"enabled": enabled, "mode": mode}


@dataclass
class RouterEvent:
    """One whitelisted router observation event (no prompt)."""

    event_type: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"event_type": self.event_type, "payload": dict(self.payload)}


@dataclass
class RouterStats:
    """In-memory counters (§70 + Sprint 1.1.1 §12-13)."""

    decisions: int = 0
    errors: int = 0
    unsafe_predictions: int = 0  # unsafe intent with canary candidate
    unsafe_predicted_read_only: int = 0  # unsafe intent seen as read-only
    matches: int = 0              # recommendation == actual route
    policy_mismatches: int = 0    # recommendation != actual (expected while
                                  # production policy keeps legacy)
    classification_reviews: int = 0  # operator-reviewed observations
    candidates: Dict[str, int] = field(default_factory=lambda: {
        "legacy": 0, "v2_shadow": 0, "v2_canary": 0,
        "require_approval": 0, "deny": 0, "unknown": 0,
    })
    recommended: Dict[str, int] = field(default_factory=lambda: {
        "legacy": 0, "shadow": 0, "canary": 0,
        "approval": 0, "deny": 0, "unknown": 0,
    })
    actual: Dict[str, int] = field(default_factory=lambda: {
        "legacy": 0, "canary": 0, "shadow": 0,
        "operations": 0, "other": 0,
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decisions": self.decisions,
            "errors": self.errors,
            "unsafe_predictions": self.unsafe_predictions,
            "unsafe_predicted_read_only": self.unsafe_predicted_read_only,
            "matches": self.matches,
            "policy_mismatches": self.policy_mismatches,
            "classification_reviews": self.classification_reviews,
            "candidates": dict(self.candidates),
            "recommended": dict(self.recommended),
            "actual": dict(self.actual),
        }


class IntentRouter:
    """OBSERVE / RECOMMEND facade — no execution authority."""

    def __init__(
        self,
        classifier: Optional[IntentClassifier] = None,
        capabilities: Optional[CapabilityRegistry] = None,
        policy: Optional[RouterPolicy] = None,
        flags: Optional[Dict[str, Any]] = None,
        event_sink: Optional[Callable[[RouterEvent], None]] = None,
        ring_size: int = 1000,
        clock=None,
        health_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        self._classifier = classifier or RuleBasedIntentClassifier()
        self._capabilities = capabilities or CapabilityRegistry()
        self._policy = policy or RouterPolicy(
            capabilities=self._capabilities
        )
        self._flags = flags if flags is not None else read_router_flags()
        mode_value = self._flags.get("mode")
        if isinstance(mode_value, RouterMode):
            self._mode = mode_value
        else:
            self._mode = parse_mode(
                mode_value.value if isinstance(mode_value, RouterMode)
                else mode_value
            )
        self._event_sink = event_sink
        self._ring: List[RouterEvent] = []
        self._ring_size = max(10, int(ring_size))
        self._stats = RouterStats()
        self._clock = clock or (lambda: time.time())
        # Health snapshot: cached (30s TTL) by default so observe() never
        # blocks on a systemctl probe per request; tests inject a stub.
        self._health_provider = health_provider or _cached_health()
        self._health_cache: Dict[str, Any] = {}
        self._health_cached_at: float = -1.0
        self._health_ttl = 30.0

    # ── core entry ───────────────────────────────────────────────────

    def observe(
        self,
        features: RequestIntentFeatures,
        actual_route: Optional[str] = None,
        sample_source: str = "LIVE",
    ) -> IntentRoutingDecision:
        """Evaluate one request and RECOMMEND. Never executes anything.

        Production hook (§57): the gateway adapter calls this AFTER its
        own routing decision; the result is logged only. The router is
        non-authoritative and fail-closed.

        ``actual_route`` is the route the gateway ACTUALLY took
        (Sprint 1.1.1 §11 — exact ActualRoute values, never inferred
        from response text); it feeds the recommendation-vs-actual
        match counters and safe telemetry only.
        """
        started = self._clock()
        try:
            return self._evaluate(features, started, actual_route,
                                  sample_source)
        except IntentRouterError:
            raise
        except Exception as exc:  # fail closed (§20)
            self._stats.errors += 1
            self._emit(RouterEvent(
                INTENT_ROUTER_ERROR,
                router_error_payload(
                    features.request_id, type(exc).__name__,
                    ROUTER_VERSION, self._mode.value,
                ),
            ))
            return self._fallback_decision(features, started)

    # ── evaluate (classification path) ───────────────────────────────

    def _evaluate(
        self,
        features: RequestIntentFeatures,
        started: float,
        actual_route: Optional[str] = None,
        sample_source: str = "LIVE",
    ) -> IntentRoutingDecision:
        classification = self._classifier.classify(features)
        flags = {
            "canary": self._flags.get("canary", False),
            "shadow": self._flags.get("shadow", False),
        }
        health = self._health_snapshot()
        policy_out = self._policy.decide(
            classification, features, flags=flags, health=health
        )

        # unsafe-prediction guard: an unsafe intent must never produce a
        # V2_CANARY candidate (§75 safety acceptance).
        unsafe = classification.intent in (
            IntentType.WRITE_ACTION, IntentType.DELETE_ACTION,
            IntentType.SYSTEM_ACTION, IntentType.SCHEDULE_ACTION,
        )
        if unsafe and policy_out["candidate_route"] in (
            "v2_canary", "v2_shadow"
        ):
            self._stats.unsafe_predictions += 1
            policy_out["candidate_route"] = "legacy"
            policy_out["effective_route"] = "legacy"
            policy_out["recommended_route"] = "legacy"
            policy_out["reason_codes"] = (
                ["unsafe_prediction_guard"] +
                list(policy_out.get("reason_codes") or [])
            )
        # Sprint 1.1.1 §13: unsafe intent classified as read-only would be
        # a safety-critical classifier failure; count it (must stay 0).
        if unsafe and classification.expected_side_effect in (
            ExpectedSideEffect.NONE, ExpectedSideEffect.READ_ONLY,
        ):
            self._stats.unsafe_predicted_read_only += 1

        decision = IntentRoutingDecision(
            request_id=features.request_id,
            intent=policy_out["intent"],
            risk=policy_out["risk"],
            expected_side_effect=policy_out["expected_side_effect"],
            recommended_route=policy_out["recommended_route"],
            candidate_route=policy_out["candidate_route"],
            effective_route=policy_out["effective_route"],
            confidence=policy_out["confidence"],
            reason_codes=list(policy_out["reason_codes"]),
            required_capabilities=list(policy_out["required_capabilities"]),
            eligible_tools=list(policy_out["eligible_tools"]),
            approval_required=policy_out["approval_required"],
            canary_eligible=policy_out["canary_eligible"],
            shadow_eligible=policy_out["shadow_eligible"],
            fallback_route=policy_out["fallback_route"],
            classifier_version=self._classifier.VERSION,
            policy_version=self._policy.VERSION,
            timestamp=_iso_timestamp(),
            duration_ms=None,
            actual_route=actual_route,
            sample_source=sample_source,
            missing_capabilities=list(
                policy_out.get("capability_gap") or []
            ),
        )
        decision.duration_ms = round(
            (self._clock() - started) * 1000.0, 3
        )
        decision.matched = _match_actual(decision.effective_route,
                                         actual_route)

        self._stats.decisions += 1
        self._stats.candidates[decision.candidate_route] = \
            self._stats.candidates.get(decision.candidate_route, 0) + 1
        self._stats.recommended[_rec_bucket(
            decision.recommended_route)] += 1
        if decision.matched is True:
            self._stats.matches += 1
        elif decision.matched is False:
            self._stats.policy_mismatches += 1
        if actual_route:
            self._stats.actual[_act_bucket(actual_route)] += 1
        self._emit(RouterEvent(
            INTENT_ROUTER_EVALUATED,
            router_event_payload(
                request_id=features.request_id,
                intent=decision.intent,
                risk=decision.risk,
                candidate_route=decision.candidate_route,
                effective_route=decision.effective_route,
                confidence=decision.confidence,
                reason_codes=decision.reason_codes,
                capabilities=decision.required_capabilities,
                duration_ms=decision.duration_ms,
                router_version=ROUTER_VERSION,
                mode=self._mode.value,
                expected_side_effect=decision.expected_side_effect,
                actual_route=actual_route,
                matched=decision.matched,
                missing_capabilities=decision.missing_capabilities,
                sample_source=sample_source,
                policy_version=self._policy.VERSION,
            ),
        ))
        return decision

    # ── helpers ──────────────────────────────────────────────────────

    def _health_snapshot(self) -> Dict[str, Any]:
        """Cached live V2 health for the policy gate (best-effort).

        Cache TTL keeps observe() sub-millisecond: a systemctl probe
        happens at most once per 30s, never per request. On any error
        the cache returns "unknown" → policy blocks V2_CANARY (fail
        closed; the gateway remains the authority regardless).
        """
        now = self._clock()
        if now - self._health_cached_at < self._health_ttl:
            return self._health_cache
        try:
            snapshot = self._health_provider()
            if not isinstance(snapshot, dict):
                snapshot = {"status": "unknown"}
        except Exception:
            snapshot = {"status": "unknown"}
        self._health_cache = snapshot
        self._health_cached_at = now
        return snapshot

    def _fallback_decision(
        self, features: RequestIntentFeatures, started: float
    ) -> IntentRoutingDecision:
        return IntentRoutingDecision(
            request_id=features.request_id,
            intent="unknown",
            risk="unknown",
            expected_side_effect="unknown",
            recommended_route="legacy",
            candidate_route="legacy",
            effective_route="legacy",
            confidence=0.0,
            reason_codes=["router_error"],
            required_capabilities=[],
            eligible_tools=[],
            approval_required=False,
            canary_eligible=False,
            shadow_eligible=False,
            fallback_route="legacy",
            classifier_version=self._classifier.VERSION,
            policy_version=self._policy.VERSION,
            timestamp=_iso_timestamp(),
            duration_ms=round((self._clock() - started) * 1000.0, 3),
        )

    def _emit(self, event: RouterEvent) -> None:
        self._ring.append(event)
        if len(self._ring) > self._ring_size:
            self._ring = self._ring[-self._ring_size:]
        if self._event_sink is not None:
            try:
                self._event_sink(event)
            except Exception:
                pass  # a broken sink must never break the router

    # ── status / inspection ──────────────────────────────────────────

    def status(self) -> RouterStatus:
        return RouterStatus(
            enabled=bool(self._flags.get("enabled")),
            mode=self._mode.value,
            router_version=ROUTER_VERSION,
            policy_version=self._policy.VERSION,
            rules=len(RULES),
            decision_count=self._stats.decisions,
            error_count=self._stats.errors,
            unsafe_count=self._stats.unsafe_predictions,
        )

    def health(self) -> Dict[str, Any]:
        """Sprint 1.1.1 §14 router health section.

        HEALTHY: unsafe=0 and error_rate<1% and p95<5ms.
        DEGRADED: latency/error warning. UNHEALTHY: unsafe>0 (or the
        router altered the actual route — impossible by construction).
        p50/p95 come from the in-memory ring (bounded, no persistence).
        """
        obs = self._stats.decisions
        errs = self._stats.errors
        durations = [
            float(e.payload["duration_ms"])
            for e in self._ring
            if e.payload.get("duration_ms") is not None
        ]

        def _pct(p: float) -> Optional[float]:
            if not durations:
                return None
            s = sorted(durations)
            idx = min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1))))
            return round(s[idx], 3)

        unsafe = self._stats.unsafe_predictions
        unsafe_readonly = self._stats.unsafe_predicted_read_only
        error_rate = round(errs / obs, 6) if obs else 0.0
        p95 = _pct(95)
        if unsafe or unsafe_readonly:
            level = "UNHEALTHY"
        elif error_rate >= 0.01 or (p95 is not None and p95 > 20.0):
            level = "DEGRADED"
        else:
            level = "HEALTHY"
        return {
            "level": level,
            "enabled": bool(self._flags.get("enabled")),
            "mode": self._mode.value,
            "observations": obs,
            "errors": errs,
            "error_rate": error_rate,
            "unsafe_canary_recommendations": unsafe,
            "unsafe_predicted_read_only": unsafe_readonly,
            "p50_ms": _pct(50),
            "p95_ms": p95,
        }

    def recent_events(self, limit: int = 20) -> List[RouterEvent]:
        return list(self._ring[-limit:])

    def stats(self) -> Dict[str, Any]:
        return self._stats.to_dict()


def _iso_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _cached_health() -> Callable[[], Dict[str, Any]]:
    """Default health provider: live OperationsService probe.

    Wrapped in the router's own 30s TTL cache; the provider itself is
    a plain callable so tests substitute a stub freely.
    """

    def _probe() -> Dict[str, Any]:
        try:
            from agent.operations_v2.service import OperationsService

            svc = OperationsService()
            health = svc.health()
            return {"status": health.status}
        except Exception:
            return {"status": "unknown"}

    return _probe


__all__ = [
    "IntentRouter",
    "RouterEvent",
    "RouterStats",
    "RouterStatus",
    "read_router_flags",
    "parse_mode",
    "ROUTER_VERSION",
    "RULES_VERSION",
]
