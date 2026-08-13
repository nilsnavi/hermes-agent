"""Model Router V1 (Sprint 0.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from agent.provider_registry import ProviderRegistry
from agent.provider_registry.events import emit

from .models_table import COST_ORDER, LATENCY_ORDER, ModelDefinition, models_for_provider
from .profiles import DEFAULT_PROFILE_ID, get_profile

# ── decision types ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FallbackCandidate:
    provider: str
    model: str
    reason: str


@dataclass(frozen=True)
class ModelRouteDecision:
    """Internal (shadow) route decision. Never carries credentials."""

    profile: str
    intent: str = ""
    provider: str = ""
    model: str = ""
    reasonCode: str = "NO_ROUTE_AVAILABLE"  # SELECTED|PROFILE_FALLBACK|MODEL_UNSUPPORTED|NO_ROUTE_AVAILABLE
    reason: str = ""
    fallbackCandidates: List[FallbackCandidate] = field(default_factory=list)
    registryHealth: str = ""
    routingEligible: bool = False
    capabilityMatch: List[str] = field(default_factory=list)
    costClass: str = ""
    latencyClass: str = ""
    decisionSource: str = "model_router_v1_shadow"
    shadow: bool = True
    rejected: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.reasonCode in ("SELECTED", "PROFILE_FALLBACK")


class ProfileError(ValueError):
    """Unknown or disabled profile."""


# ── scoring weights (§10 — deterministic, transparent) ────────────────────

_HEALTH_WEIGHT = {"HEALTHY": 100.0, "DEGRADED": 70.0, "UNKNOWN": 45.0}
_PROFILE_PREF = 50.0
_PRIORITY_WEIGHT = 12.0
_COST_WEIGHT = 6.0
_LATENCY_WEIGHT = 5.0
_CAPABILITY_PREF = 2.0
_FAILURE_PENALTY = 2.0

_USABLE_HEALTH = ("HEALTHY", "DEGRADED")
_BAD_AUTH = ("INVALID", "EXPIRED", "MISSING", "UNSUPPORTED")


class ModelRouter:
    """Deterministic profile → (provider, model) router over ProviderRegistry."""

    def __init__(self, registry: Optional[ProviderRegistry] = None) -> None:
        self._registry = registry or ProviderRegistry()

    # ── public API ────────────────────────────────────────────────────────

    def route_model(
        self,
        profile: str = DEFAULT_PROFILE_ID,
        intent: str = "",
        requiredCapabilities: Optional[List[str]] = None,
        preferredCapabilities: Optional[List[str]] = None,
        preferredProvider: Optional[str] = None,
        excludedProviders: Optional[List[str]] = None,
        maxCostClass: Optional[str] = None,
        requiresTools: Optional[bool] = None,
        allow_unknown_health: bool = False,
        explicit: Optional[Tuple[str, str]] = None,
    ) -> ModelRouteDecision:
        """Route a profile to a concrete provider/model (shadow, no side effects)."""
        prof = get_profile(profile)
        if prof is None:
            raise ProfileError(f"unknown profile: {profile!r}")
        if not prof.enabled:
            raise ProfileError(f"profile disabled: {profile!r}")

        emit("model.route.requested", status="ok",
             extra={"profile": prof.id, "intent": (intent or "")[:80]})

        if explicit is not None:
            decision = self._route_explicit(prof, intent, explicit, allow_unknown_health)
        else:
            decision = self._route_profile(
                prof, intent,
                req_caps=requiredCapabilities,
                pref_caps=preferredCapabilities,
                preferred_provider=preferredProvider,
                excluded=excludedProviders,
                max_cost=maxCostClass,
                requires_tools=requiresTools,
                allow_unknown_health=allow_unknown_health,
            )
        return decision

    def fallback_candidates(
        self,
        profile: str = DEFAULT_PROFILE_ID,
        excluded: Optional[List[str]] = None,
    ) -> List[FallbackCandidate]:
        """Candidates for `profile` from eligible providers only (§12)."""
        prof = get_profile(profile)
        if prof is None or not prof.enabled:
            return []
        excluded_ids = set(excluded or [])
        required = set(prof.requiredCapabilities or [])
        if prof.requiresTools:
            required.add("TOOL_CALLING")
        scored: List[Tuple[float, ModelDefinition]] = []
        for p in self._registry.list_providers():
            if p.id in excluded_ids or p.id in set(prof.excludedProviders):
                continue
            st = self._status(p.id)
            if not self._provider_usable_base(st):
                continue
            for md in models_for_provider(p.id):
                if not md.enabled or not md.has_all(list(required)):
                    continue
                scored.append((self._score(md, prof, st, prof.preferredCapabilities), md))
        scored.sort(key=lambda t: (-t[0], t[1].provider, t[1].model))
        return [
            FallbackCandidate(provider=md.provider, model=md.model,
                              reason=f"score={s:.2f}")
            for s, md in scored[:4]
        ]

    def profile_available(self, profile_id: str) -> bool:
        prof = get_profile(profile_id)
        if prof is None or not prof.enabled:
            return False
        return self._profile_possible(prof)

    # ── explicit override path (§17) ──────────────────────────────────────

    def _route_explicit(self, prof, intent: str, explicit: Tuple[str, str],
                        allow_unknown_health: bool) -> ModelRouteDecision:
        provider, model = explicit
        md = self._find_model(provider, model)
        st = self._status(provider)
        usable = md is not None and self._provider_usable(
            st, allow_unknown_health or prof.allowUnknownHealth)
        if not usable:
            reason = "not in model table" if md is None else self._reject_reason(st)
            d = ModelRouteDecision(
                profile=prof.id, intent=intent, provider=provider, model=model,
                reasonCode="MODEL_UNSUPPORTED",
                reason=f"explicit {provider}/{model} not usable: {reason}",
                rejected=[f"{provider}/{model} — {reason}"],
                fallbackCandidates=self.fallback_candidates(prof.id),
            )
            emit("model.route.no_route", status="error",
                 extra={"profile": prof.id, "provider": provider, "model": model,
                        "reasonCode": "MODEL_UNSUPPORTED"})
            return d
        assert md is not None
        d = ModelRouteDecision(
            profile=prof.id, intent=intent, provider=provider, model=model,
            reasonCode="SELECTED", reason="explicit override usable",
            routingEligible=True,
            fallbackCandidates=self.fallback_candidates(prof.id),
            capabilityMatch=list(md.capabilities),
            costClass=md.costClass, latencyClass=md.latencyClass,
            registryHealth=self._health_summary(),
        )
        emit("model.route.selected", status="ok",
             extra={"profile": prof.id, "provider": provider, "model": model,
                    "reasonCode": "EXPLICIT_OVERRIDE"})
        return d

    # ── profile path (§8) ─────────────────────────────────────────────────

    def _route_profile(self, prof, intent: str, req_caps, pref_caps, preferred_provider,
                       excluded, max_cost, requires_tools, allow_unknown_health) -> ModelRouteDecision:
        original_id = prof.id

        # §13: graceful degradation only when explicitly allowed
        chain: List[str] = []
        effective = prof
        while not self._profile_possible(effective, req_caps) and effective.fallbackProfile:
            nxt = get_profile(effective.fallbackProfile)
            if nxt is None or nxt.id == effective.id or nxt.id in chain:
                break
            chain.append(effective.id)
            emit("model.profile.resolved", status="ok",
                 extra={"profile": effective.id, "resolvedTo": nxt.id,
                        "reason": "graceful_degradation"})
            effective = nxt

        required = set(effective.requiredCapabilities or [])
        if requires_tools or effective.requiresTools:
            required.add("TOOL_CALLING")
        required.update(req_caps or [])
        prefs = list(dict.fromkeys((pref_caps or []) + (effective.preferredCapabilities or [])))
        excluded_ids = set(excluded or []) | set(effective.excludedProviders or [])
        pref_provider = (preferred_provider or "").strip().lower()

        scored: List[Tuple[float, ModelDefinition, dict]] = []
        for p in self._registry.list_providers():
            pid = p.id
            if pid in excluded_ids:
                continue
            if pref_provider and pid != pref_provider:
                continue
            st = self._status(pid)
            if not self._provider_usable(
                st, allow_unknown_health or effective.allowUnknownHealth):
                continue
            for md in models_for_provider(pid):
                if not md.enabled or not md.has_all(list(required)):
                    continue
                if max_cost and COST_ORDER.get(md.costClass, 0) > COST_ORDER.get(max_cost, 0):
                    continue
                # latency: profile.maxLatencyClass = "not slower than" — FAST(3) is
                # faster than NORMAL(2); reject only models slower than the cap
                if LATENCY_ORDER.get(md.latencyClass, 0) < LATENCY_ORDER.get(effective.maxLatencyClass, 0):
                    continue
                score = self._score(md, effective, st, prefs)
                scored.append((score, md, st or {}))

        if not scored:
            d = ModelRouteDecision(
                profile=original_id, intent=intent,
                reasonCode="NO_ROUTE_AVAILABLE",
                reason="no eligible provider/model for profile",
                registryHealth=self._health_summary(),
            )
            emit("model.route.no_route", status="error",
                 extra={"profile": original_id, "reasonCode": "NO_ROUTE_AVAILABLE"})
            return d

        # §8/§29 deterministic ordering: score desc → provider id → model id
        scored.sort(key=lambda t: (-t[0], t[1].provider, t[1].model))
        best_score, best_md, best_st = scored[0]
        fallbacks = [
            FallbackCandidate(provider=md.provider, model=md.model,
                              reason=f"score={score:.2f}")
            for score, md, _st in scored[1:4]
        ]
        reason_code = "PROFILE_FALLBACK" if chain else "SELECTED"
        reason_text = ("profile degraded " + ">".join(chain)) if chain else f"score={best_score:.2f}"
        d = ModelRouteDecision(
            profile=effective.id, intent=intent,
            provider=best_md.provider, model=best_md.model,
            reasonCode=reason_code, reason=reason_text,
            fallbackCandidates=fallbacks,
            registryHealth=self._health_summary(),
            routingEligible=True,
            capabilityMatch=list(best_md.capabilities),
            costClass=best_md.costClass, latencyClass=best_md.latencyClass,
        )
        emit("model.route.selected", status="ok",
             extra={"profile": effective.id, "provider": best_md.provider,
                    "model": best_md.model, "reasonCode": reason_code})
        for fb in fallbacks:
            emit("model.route.fallback_candidate", status="ok",
                 extra={"profile": effective.id, "provider": fb.provider,
                        "model": fb.model})
        return d

    # ── scoring (§10) ─────────────────────────────────────────────────────

    def _score(self, md, prof, st, prefs: List[str]) -> float:
        s = 0.0
        health = (st or {}).get("healthStatus", "UNKNOWN")
        s += _HEALTH_WEIGHT.get(health, 0.0)
        if prof.preferredProviders and md.provider in prof.preferredProviders:
            rank = len(prof.preferredProviders) - prof.preferredProviders.index(md.provider)
            s += _PROFILE_PREF + rank
        try:
            p = next(x for x in self._registry.list_providers() if x.id == md.provider)
            if p.priority is not None:
                s += _PRIORITY_WEIGHT / max(1, p.priority)
        except StopIteration:
            pass
        s += _CAPABILITY_PREF * len(set(md.capabilities) & set(prefs))
        s += _COST_WEIGHT * COST_ORDER.get(md.costClass, 0)
        s += _LATENCY_WEIGHT * LATENCY_ORDER.get(md.latencyClass, 0)
        failures = int((st or {}).get("consecutiveFailures", 0) or 0)
        s -= _FAILURE_PENALTY * min(failures, 5)
        return round(s, 3)

    # ── capability/eligibility helpers ────────────────────────────────────

    def _profile_possible(self, prof, req_caps=None) -> bool:
        required = set(prof.requiredCapabilities or [])
        if prof.requiresTools:
            required.add("TOOL_CALLING")
        required.update(req_caps or [])
        for p in self._registry.list_providers():
            if p.id in set(prof.excludedProviders):
                continue
            st = self._status(p.id)
            if not self._provider_usable(st, prof.allowUnknownHealth):
                continue
            for md in models_for_provider(p.id):
                if md.enabled and md.has_all(list(required)):
                    return True
        return False

    def _provider_usable(self, st, allow_unknown: bool = False) -> bool:
        if not st:
            return False
        if st.get("routingEligible") is not True:
            return False
        if st.get("enabled") is not True:
            return False
        if st.get("authStatus") in _BAD_AUTH:
            return False
        if st.get("availabilityReason") in ("AUTH", "GEO_BLOCKED", "WAF_BLOCKED"):
            return False
        health = st.get("healthStatus")
        if health in _USABLE_HEALTH:
            return True
        if health == "UNKNOWN" and allow_unknown:
            return True
        return False

    def _provider_usable_base(self, st) -> bool:
        """Filter used for fallback candidates (§12): strict, broken never included."""
        if not st:
            return False
        if st.get("circuitState") == "OPEN":
            return False
        if st.get("authStatus") in _BAD_AUTH:
            return False
        if st.get("availabilityReason") in ("AUTH", "GEO_BLOCKED", "WAF_BLOCKED"):
            return False
        return st.get("routingEligible") is True

    def _reject_reason(self, st) -> str:
        if not st:
            return "NOT_REGISTERED"
        auth = st.get("authStatus")
        if auth in _BAD_AUTH:
            return f"AUTH_{auth}"
        if st.get("circuitState") == "OPEN":
            return "CIRCUIT_OPEN"
        reason = st.get("availabilityReason")
        if reason and reason not in ("NONE", "ELIGIBLE"):
            return reason
        return f"health={st.get('healthStatus')}"

    def _status(self, provider_id: str) -> Optional[dict]:
        try:
            return self._registry.get_provider_status(provider_id)
        except Exception:
            return None

    def _find_model(self, provider: str, model: str) -> Optional[ModelDefinition]:
        for md in models_for_provider(provider):
            if md.model == model or model in md.aliases:
                return md
        return None

    def _health_summary(self) -> str:
        parts = []
        for p in self._registry.list_providers():
            st = self._status(p.id)
            parts.append(f"{p.id}={(st or {}).get('healthStatus', '?')}")
        return " ".join(parts[:8])


# ── shadow mode helper (§15) ──────────────────────────────────────────────


def shadow_compare(
    router: ModelRouter,
    legacy_provider: str,
    legacy_model: str,
    profile: str = DEFAULT_PROFILE_ID,
    intent: str = "",
) -> ModelRouteDecision:
    """What would V2 select for this legacy (provider, model) pair? Log and return."""
    decision = router.route_model(profile=profile, intent=intent)
    same = bool(
        decision.ok
        and decision.provider == legacy_provider
        and decision.model == legacy_model
    )
    emit("model.route.shadow_compare", status="ok",
         extra={
             "legacyProvider": legacy_provider,
             "legacyModel": legacy_model,
             "routerProvider": decision.provider if decision.ok else "",
             "routerModel": decision.model if decision.ok else "",
             "same": same,
             "reasonCode": decision.reasonCode,
             "reason": "match" if same else "mismatch",
         })
    return decision