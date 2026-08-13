"""Model Router V1 tests (Sprint 0.5 §25–§30)."""

import os
import pytest

from agent.provider_registry import (
    AvailabilityReason,
    CircuitState,
    ProviderAuthStatus,
    ProviderDefinition,
    ProviderHealthStatus,
    ProviderRegistry,
)
from agent.model_router import (
    ModelRouteDecision,
    ModelRouter,
    ProfileError,
    router_v2_enabled,
    shadow_enabled,
    shadow_compare,
)
from agent.model_router.models_table import find_model, register_model, ModelDefinition


# ── fixtures ──────────────────────────────────────────────────────────────


def _def_provider(pid: str, priority: int = 100, enabled: bool = True) -> ProviderDefinition:
    return ProviderDefinition(id=pid, displayName=pid, priority=priority, enabled=enabled)


def build_registry() -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register_provider(
        _def_provider("opencode", priority=1),
        initial_health=ProviderHealthStatus.HEALTHY,
        initial_auth=ProviderAuthStatus.VALID,
        initial_reason=AvailabilityReason.NONE,
        initial_eligible=True,
    )
    reg.register_provider(
        _def_provider("deepseek"),
        initial_health=ProviderHealthStatus.HEALTHY,
        initial_auth=ProviderAuthStatus.VALID,
        initial_reason=AvailabilityReason.NONE,
        initial_eligible=True,
    )
    reg.register_provider(
        _def_provider("claudehub"),
        initial_health=ProviderHealthStatus.UNAVAILABLE,
        initial_auth=ProviderAuthStatus.INVALID,
        initial_reason=AvailabilityReason.AUTH,
        initial_eligible=False,
    )
    reg.register_provider(
        _def_provider("openrouter"),
        initial_health=ProviderHealthStatus.UNAVAILABLE,
        initial_auth=ProviderAuthStatus.VALID,
        initial_reason=AvailabilityReason.WAF_BLOCKED,
        initial_eligible=False,
    )
    reg.register_provider(
        _def_provider("nous"),
        initial_health=ProviderHealthStatus.UNAVAILABLE,
        initial_auth=ProviderAuthStatus.EXPIRED,
        initial_reason=AvailabilityReason.AUTH,
        initial_eligible=False,
    )
    return reg


@pytest.fixture
def router() -> ModelRouter:
    return ModelRouter(registry=build_registry())


# ── §25 profile resolution ────────────────────────────────────────────────

def test_fast_resolves(router):
    d = router.route_model(profile="FAST")
    assert d.ok
    assert d.provider in ("opencode", "deepseek")
    assert d.model  # non-empty


def test_balanced_resolves(router):
    d = router.route_model(profile="BALANCED")
    assert d.ok
    assert d.provider == "opencode"
    assert d.model == "deepseek-v4-flash-free"
    assert d.costClass == "FREE"
    assert d.latencyClass == "FAST"


def test_reasoning_resolves(router):
    # no verified REASONING-capable model; REASONING capability is *preferred*
    # (not required) → profile still resolves to best available
    d = router.route_model(profile="REASONING")
    assert d.ok
    assert d.provider == "opencode"
    assert d.model == "deepseek-v4-flash-free"


def test_profile_fallback_when_required_cap_absent(router):
    # profile whose *required* capability is not verified anywhere
    # → graceful degradation through fallbackProfile, not broken chain
    from agent.model_router.profiles import (
        ModelProfile,
        register_profile,
        unregister_profile,
    )

    register_profile(
        ModelProfile(
            id="VISIONX",
            requiredCapabilities=["VISION"],
            fallbackProfile="BALANCED",
            maxLatencyClass="SLOW",
            maxCostClass="HIGH",
            enabled=True,
        )
    )
    try:
        d = router.route_model(profile="VISIONX")
        assert d.ok
        assert d.reasonCode == "PROFILE_FALLBACK"
        assert d.provider == "opencode"
    finally:
        unregister_profile("VISIONX")


def test_coding_no_route(router):
    # CODING requires verified CODING capability; none registered
    d = router.route_model(profile="CODING")
    assert not d.ok
    assert d.reasonCode == "NO_ROUTE_AVAILABLE"


def test_unknown_profile_rejected(router):
    with pytest.raises(ProfileError):
        router.route_model(profile="NOSUCH")


def test_disabled_profile_rejected(router):
    from agent.model_router.profiles import ModelProfile
    from agent.model_router.profiles import register_profile, unregister_profile

    register_profile(ModelProfile(id="OFF", enabled=False))
    try:
        with pytest.raises(ProfileError):
            router.route_model(profile="OFF")
    finally:
        unregister_profile("OFF")


def test_vision_required_no_route(router):
    d = router.route_model(profile="FAST", requiredCapabilities=["VISION"])
    assert d.reasonCode == "NO_ROUTE_AVAILABLE"


# ── §26 provider filtering ────────────────────────────────────────────────

def test_degraded_allowed_with_penalty(router):
    router._registry.update_health("deepseek", health_status=ProviderHealthStatus.DEGRADED)
    d = router.route_model(profile="BALANCED")
    assert d.ok and d.provider == "opencode"  # healthy primary wins
    # only deepseek present → degraded allowed but lower score
    reg2 = ProviderRegistry()
    reg2.register_provider(
        _def_provider("deepseek"),
        initial_health=ProviderHealthStatus.DEGRADED,
        initial_auth=ProviderAuthStatus.VALID,
        initial_reason=AvailabilityReason.NONE,
        initial_eligible=True,
    )
    d2 = ModelRouter(reg2).route_model(profile="BALANCED")
    assert d2.ok and d2.provider == "deepseek"


def test_unavailable_excluded(router):
    reg = ProviderRegistry()
    reg.register_provider(
        _def_provider("opencode", priority=1),
        initial_health=ProviderHealthStatus.UNAVAILABLE,
        initial_auth=ProviderAuthStatus.VALID,
        initial_reason=AvailabilityReason.NONE,
        initial_eligible=False,
    )
    d = ModelRouter(reg).route_model(profile="BALANCED")
    assert d.reasonCode == "NO_ROUTE_AVAILABLE"


def test_disabled_provider_excluded(router):
    reg = ProviderRegistry()
    reg.register_provider(
        _def_provider("opencode", priority=1, enabled=False),
        initial_health=ProviderHealthStatus.HEALTHY,
        initial_auth=ProviderAuthStatus.VALID,
        initial_reason=AvailabilityReason.NONE,
        initial_eligible=True,
    )
    d = ModelRouter(reg).route_model(profile="BALANCED")
    assert d.reasonCode == "NO_ROUTE_AVAILABLE"


def test_circuit_open_excluded(router):
    router._registry.open_circuit("opencode")
    d = router.route_model(profile="BALANCED")
    assert d.ok and d.provider == "deepseek"  # opencode out, deepseek in


def test_auth_invalid_excluded(router):
    reg = ProviderRegistry()
    reg.register_provider(
        _def_provider("claudehub"),
        initial_health=ProviderHealthStatus.HEALTHY,
        initial_auth=ProviderAuthStatus.INVALID,
        initial_reason=AvailabilityReason.NONE,
        initial_eligible=True,  # even if registry marks eligible, router must refuse
    )
    d = ModelRouter(reg).route_model(profile="BALANCED")
    assert d.reasonCode == "NO_ROUTE_AVAILABLE"


def test_auth_expired_excluded(router):
    reg = ProviderRegistry()
    reg.register_provider(
        _def_provider("nous"),
        initial_health=ProviderHealthStatus.HEALTHY,
        initial_auth=ProviderAuthStatus.EXPIRED,
        initial_reason=AvailabilityReason.NONE,
        initial_eligible=True,
    )
    d = ModelRouter(reg).route_model(profile="BALANCED")
    assert d.reasonCode == "NO_ROUTE_AVAILABLE"


def test_waf_geo_excluded(router):
    for reason in (AvailabilityReason.WAF_BLOCKED, AvailabilityReason.GEO_BLOCKED):
        reg = ProviderRegistry()
        reg.register_provider(
            _def_provider("openrouter"),
            initial_health=ProviderHealthStatus.UNAVAILABLE,
            initial_auth=ProviderAuthStatus.VALID,
            initial_reason=reason,
            initial_eligible=True,
        )
        d = ModelRouter(reg).route_model(profile="BALANCED")
        assert d.reasonCode == "NO_ROUTE_AVAILABLE"


# ── §27 broken fallback acceptance ────────────────────────────────────────

def test_broken_providers_never_candidates(router):
    d = router.route_model(profile="BALANCED")
    assert d.ok and d.provider == "opencode"
    broken = {"claudehub", "openrouter", "nous"}
    for cand in d.fallbackCandidates:
        assert cand.provider not in broken


def test_broken_fallback_list_excludes_all(router):
    cands = router.fallback_candidates("BALANCED")
    broken = {"claudehub", "openrouter", "nous"}
    assert all(c.provider not in broken for c in cands)


# ── §28 unsupported model ────────────────────────────────────────────────

def test_explicit_unsupported_model_no_broken_chain(router):
    d = router.route_model(profile="BALANCED", explicit=("opencode", "minimax-m3-free"))
    assert d.reasonCode == "MODEL_UNSUPPORTED"
    # no silent broken fallback: never claudehub
    assert all(c.provider != "claudehub" for c in d.fallbackCandidates)
    # compatible candidate proposed
    assert any(
        c.provider == "opencode" and c.model == "deepseek-v4-flash-free"
        for c in d.fallbackCandidates
    )


def test_explicit_valid_override(router):
    d = router.route_model(profile="BALANCED", explicit=("opencode", "deepseek-v4-flash-free"))
    assert d.reasonCode == "SELECTED"
    assert d.provider == "opencode"


# ── §29 determinism ───────────────────────────────────────────────────────

def test_determinism_100_runs(router):
    results = set()
    for _ in range(100):
        d = router.route_model(profile="BALANCED", intent="determinism")
        results.add((d.provider, d.model, d.reasonCode, d.reason))
    assert len(results) == 1


def test_determinism_all_profiles(router):
    for profile in ("FAST", "BALANCED", "REASONING", "CODING"):
        first = router.route_model(profile=profile)
        for _ in range(50):
            nxt = router.route_model(profile=profile)
            assert (nxt.provider, nxt.model, nxt.reasonCode) == (
                first.provider, first.model, first.reasonCode)


# ── §30 feature flags ─────────────────────────────────────────────────────

def test_feature_flag_defaults():
    assert router_v2_enabled() is False
    assert shadow_enabled() is False


def test_feature_flag_env_switch(monkeypatch):
    monkeypatch.setenv("HERMES_MODEL_ROUTER_V2", "true")
    assert router_v2_enabled() is True
    monkeypatch.setenv("HERMES_MODEL_ROUTER_SHADOW", "true")
    assert shadow_enabled() is True


# ── §15 shadow comparison ─────────────────────────────────────────────────

def test_shadow_compare_match(router):
    d = shadow_compare(
        router, "opencode", "deepseek-v4-flash-free", profile="BALANCED"
    )
    assert d.ok


def test_shadow_compare_mismatch_reported(router):
    d = shadow_compare(router, "deepseek", "deepseek-chat", profile="BALANCED")
    assert d.ok and d.provider == "opencode"  # router disagrees → mismatch event


# ── §18 strict aliases ────────────────────────────────────────────────────

def test_alias_resolution_strict():
    md = find_model("deepseek", "deepseek-v4-flash")
    assert md is not None and md.model == "deepseek-chat"
    assert find_model("opencode", "deepseek-v4-flash") is None  # no cross-provider alias
    assert find_model("deepseek", "deepseek-v4-flash-free") is None


# ── model table hygiene ───────────────────────────────────────────────────

def test_primary_model_represented():
    md = find_model("opencode", "deepseek-v4-flash-free")
    assert md is not None
    assert md.verified is True
    assert "TOOL_CALLING" in md.capabilities
    assert not md.has_all(["REASONING"])  # never invent unverified capability