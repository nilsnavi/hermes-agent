"""Sprint 0.4 acceptance tests — Provider Registry V1 (16 cases)."""

from __future__ import annotations

import os
import time

import pytest

from agent.provider_registry import (
    AvailabilityReason,
    CircuitState,
    ProviderAuthStatus,
    ProviderDefinition,
    ProviderHealthStatus,
    ProviderRegistry,
    flag_enabled,
    get_registry,
    set_flag,
    shutdown_registry,
)
from agent.provider_registry.bootstrap import build_registry
from agent.provider_registry.circuit import CircuitBreaker
from agent.provider_registry.classifier import (
    CircuitImpact,
    Classification,
    ProviderErrorClass,
    ProviderErrorClassifier,
)
from agent.provider_registry.events import emit, scrub
from agent.provider_registry.health import HealthChecker, ProbeResult
from agent.provider_registry.retry import RetryPolicy


# ── helpers ──────────────────────────────────────────────────────────────

def _def(pid: str, **kw) -> ProviderDefinition:
    d = ProviderDefinition(
        id=pid,
        authType=kw.pop("authType", "api_key"),
        displayName=kw.pop("displayName", pid),
        credentialConfigured=kw.pop("credentialConfigured", True),
        defaultModel=kw.pop("defaultModel", "test-model"),
        priority=kw.pop("priority", 100),
    )
    for k, v in kw.items():
        if hasattr(d, k) and not k.startswith("_"):
            setattr(d, k, v)
    return d


@pytest.fixture(autouse=True)
def _clean_flag():
    os.environ.pop("HERMES_PROVIDER_REGISTRY_V2", None)
    yield
    os.environ.pop("HERMES_PROVIDER_REGISTRY_V2", None)
    shutdown_registry()


def _reg(breaker=None) -> ProviderRegistry:
    return ProviderRegistry(circuit=breaker)


# 1 ── feature flag: default off, toggle both ways
def test_flag_default_off_and_toggle():
    assert flag_enabled() is False
    set_flag(True)
    assert flag_enabled() is True
    set_flag(False)
    assert flag_enabled() is False
    assert "HERMES_PROVIDER_REGISTRY_V2" not in os.environ


# 2 ── singleton gated by flag: off = nothing executes
def test_get_registry_gated_by_flag():
    assert get_registry() is None
    set_flag(True)
    r1 = get_registry()
    assert r1 is not None
    assert get_registry() is r1
    set_flag(False)
    shutdown_registry()
    assert get_registry() is None


# 3 ── registration + snapshot carries no secrets
def test_register_and_snapshot_no_secrets():
    reg = _reg()
    reg.register_provider(
        _def("deepseek", defaultModel="deepseek-chat"),
        initial_health=ProviderHealthStatus.HEALTHY,
        initial_auth=ProviderAuthStatus.VALID,
        initial_reason=AvailabilityReason.NONE,
        initial_eligible=True,
    )
    got = reg.get_provider("deepseek")
    assert got is not None and got.id == "deepseek"
    snap = reg.get_provider_status("deepseek")
    assert snap["healthStatus"] == "HEALTHY"
    assert snap["routingEligible"] is True
    assert "apiKey" not in snap and "token" not in snap and "env" not in snap


# 4 ── health/auth/reason/eligibility transitions
def test_update_health_transitions():
    reg = _reg()
    reg.register_provider(_def("x"), initial_health=ProviderHealthStatus.UNKNOWN,
                          initial_eligible=False)
    assert reg.update_health("x", health_status=ProviderHealthStatus.DEGRADED,
                             availability_reason=AvailabilityReason.RATE_LIMIT,
                             routing_eligible=False) is True
    s = reg.get_provider_status("x")
    assert s["healthStatus"] == "DEGRADED"
    assert s["availabilityReason"] == "RATE_LIMIT"
    assert reg.update_health("nope", health_status=ProviderHealthStatus.HEALTHY) is False


# 5 ── success resets state and closes an open circuit
def test_record_success_clears_state_and_closes_circuit():
    reg = _reg()
    reg.register_provider(_def("y"), initial_health=ProviderHealthStatus.UNAVAILABLE,
                          initial_reason=AvailabilityReason.AUTH)
    d = reg.get_provider("y")
    d.circuitState = CircuitState.OPEN
    d.circuitOpenedAt = time.time()
    assert reg.record_success("y", http_status=200, duration_ms=12.0) is True
    s = reg.get_provider_status("y")
    assert s["healthStatus"] == "HEALTHY"
    assert s["circuitState"] == "CLOSED"
    assert s["availabilityReason"] == "NONE"
    assert s["consecutiveFailures"] == 0
    assert s["routingEligible"] is True  # closed circuit → eligible again


# 6 ── circuit breaker: threshold → OPEN, cooldown → HALF_OPEN probe, success → CLOSED
def test_circuit_breaker_flows():
    breaker = CircuitBreaker(failure_threshold=3, open_cooldown_seconds=0.1)
    reg = _reg(breaker)
    reg.register_provider(_def("cb"), initial_auth=ProviderAuthStatus.VALID)
    cls = Classification(error_class=ProviderErrorClass.NETWORK_TIMEOUT, retryable=True,
                         circuit_impact=CircuitImpact.LOW,
                         availability_reason=AvailabilityReason.NETWORK)
    reg.record_failure("cb", cls)
    reg.record_failure("cb", cls)
    assert reg.get_provider_status("cb")["circuitState"] == "CLOSED"
    assert reg.get_provider_status("cb")["healthStatus"] == "DEGRADED"
    reg.record_failure("cb", cls)  # third → open
    assert reg.get_provider_status("cb")["circuitState"] == "OPEN"
    assert reg.is_routing_eligible("cb") is False
    time.sleep(0.12)  # cooldown elapsed
    assert reg.circuit_state("cb") == "HALF_OPEN"          # lazy transition
    assert reg.is_routing_eligible("cb") is True           # probe allowed
    reg.record_success("cb", http_status=200)              # probe success closes
    assert reg.get_provider_status("cb")["circuitState"] == "CLOSED"
    assert reg.is_routing_eligible("cb") is True
    assert reg.get_provider_status("cb")["healthStatus"] == "HEALTHY"


# 7 ── permanent auth failure: routing disabled immediately, no circuit churn
def test_permanent_failure_disables_routing_no_circuit():
    reg = _reg()
    reg.register_provider(_def("z"), initial_auth=ProviderAuthStatus.VALID)
    cls = Classification(error_class=ProviderErrorClass.AUTH_INVALID, retryable=False,
                         circuit_impact=CircuitImpact.HIGH,
                         availability_reason=AvailabilityReason.AUTH)
    reg.record_failure("z", cls, http_status=401)
    s = reg.get_provider_status("z")
    assert s["healthStatus"] == "UNAVAILABLE"
    assert s["routingEligible"] is False
    assert s["circuitState"] == "CLOSED"  # no circuit churn
    assert s["authStatus"] == "INVALID"


# 8 ─── WAF beats auth taxonomy (OpenRouter 403 must never be "invalid key")
def test_openrouter_403_is_waf_not_invalid_key():
    clf = ProviderErrorClassifier()
    c = clf.classify(provider="openrouter", http_status=403,
                     message="Access denied by security policy")
    assert c.error_class == ProviderErrorClass.WAF_BLOCKED
    assert c.error_class != ProviderErrorClass.AUTH_INVALID
    assert c.retryable is False
    assert c.availability_reason == AvailabilityReason.WAF_BLOCKED
    reg = _reg()
    reg.register_provider(_def("openrouter"), initial_auth=ProviderAuthStatus.VALID)
    reg.record_failure("openrouter", c, http_status=403)
    s = reg.get_provider_status("openrouter")
    assert s["authStatus"] == "VALID"                  # platform block ≠ credential
    assert s["availabilityReason"] == "WAF_BLOCKED"


# 9 ── geo block marker beats auth markers
def test_geo_block_takes_priority():
    clf = ProviderErrorClassifier()
    c = clf.classify(provider="openai-api", http_status=403,
                     message="Access denied: unsupported_country_region_territory")
    assert c.error_class == ProviderErrorClass.GEO_BLOCKED
    assert c.availability_reason == AvailabilityReason.GEO_BLOCKED


# 10 ── expired token → AUTH_EXPIRED, provider NOT healthy
def test_expired_token_is_expired_auth():
    clf = ProviderErrorClassifier()
    c = clf.classify(provider="nous", http_status=401, message="Token has expired")
    assert c.error_class == ProviderErrorClass.AUTH_EXPIRED
    reg = _reg()
    reg.register_provider(_def("nous"))
    reg.record_failure("nous", c, http_status=401)
    s = reg.get_provider_status("nous")
    assert s["authStatus"] == "EXPIRED"
    assert s["healthStatus"] == "UNAVAILABLE"  # expired nous ≠ healthy fallback


# 11 ── health checker: due/not-due by TTL, success folds models in
def test_health_probe_ttl_jitter_and_apply():
    reg = _reg()
    reg.register_provider(_def("dd"), initial_health=ProviderHealthStatus.UNKNOWN)
    checker = HealthChecker(reg, env={}, credentials={}, ttl_map={
        "healthy": 60, "degraded": 30, "unavailable": 1e9,
    })
    d = reg.get_provider("dd")
    assert d is not None
    assert checker.due(d) is True               # never checked → due
    reg.record_success("dd", http_status=200)   # marks healthCheckedAt
    assert checker.due(d) is False
    d.healthCheckedAt = time.time() - 121         # TTL (60±20%) expired for sure
    assert checker.due(d) is True
    reg.update_health(
        "dd",
        health_status=ProviderHealthStatus.UNAVAILABLE,
        availability_reason=AvailabilityReason.NETWORK,
        routing_eligible=False,
    )
    checker._apply(d, ProbeResult("dd", True, 200, "", "NONE", 1.0, ["m1"]))
    assert reg.get_provider_status("dd")["healthStatus"] == "HEALTHY"
    assert reg.get_provider_status("dd")["availableModelsCount"] == 1


# 12 ── fallback candidates: primary excluded, broken excluded, healthy remain
def test_fallback_candidates():
    reg = _reg()
    prim = _def("opencode", priority=1, defaultModel="deepseek-v4-flash-free")
    prim.metadata = {"primary": True}
    reg.register_provider(prim, initial_health=ProviderHealthStatus.HEALTHY,
                          initial_auth=ProviderAuthStatus.VALID,
                          initial_eligible=True)
    reg.register_provider(_def("claudehub"), initial_health=ProviderHealthStatus.HEALTHY,
                          initial_auth=ProviderAuthStatus.VALID, initial_eligible=True)
    reg.register_provider(_def("deepseek"), initial_health=ProviderHealthStatus.HEALTHY,
                          initial_auth=ProviderAuthStatus.VALID, initial_eligible=True)
    reg.register_provider(_def("agentrouter"), initial_health=ProviderHealthStatus.UNAVAILABLE,
                          initial_reason=AvailabilityReason.AUTH, initial_eligible=False)
    cands = reg.get_fallback_candidates()
    ids = [c["id"] for c in cands]
    assert "opencode" not in ids
    assert "agentrouter" not in ids
    assert set(ids) == {"claudehub", "deepseek"}


# 13 ── routing eligibility reasons
def test_routing_eligibility_reason():
    reg = _reg()
    reg.register_provider(_def("down"), initial_health=ProviderHealthStatus.UNAVAILABLE,
                          initial_reason=AvailabilityReason.WAF_BLOCKED, initial_eligible=False)
    reg.register_provider(_def("ok"), initial_health=ProviderHealthStatus.HEALTHY,
                          initial_eligible=True)
    assert reg.routing_eligibility_reason("down") == "WAF_BLOCKED"
    assert reg.routing_eligibility_reason("ok") == "ELIGIBLE"
    assert reg.routing_eligibility_reason("ghost") == "NOT_REGISTERED"


# 14 ── ambiguous 403 (no markers) → UNKNOWN, non-retryable, routing disabled
def test_ambiguous_403_non_retryable():
    clf = ProviderErrorClassifier()
    c = clf.classify(provider="any", http_status=403, message="denied for unknown reasons")
    assert c.error_class == ProviderErrorClass.UNKNOWN
    assert c.retryable is False
    assert c.circuit_impact == CircuitImpact.HIGH
    reg = _reg()
    reg.register_provider(_def("u"), initial_eligible=True)
    reg.record_failure("u", c, http_status=403)
    assert reg.is_routing_eligible("u") is False


# 15 ── bootstrap: build from config/env dicts, no secrets leaked
def test_bootstrap_builds_registry():
    cfg = {
        "model": {"provider": "opencode", "default": "deepseek-v4-flash-free"},
        "fallback_providers": [
            {"base_url": "https://api.claudehub.fun/v1", "model": "claude-sonnet-4.6", "api_key": "sk-fake-custom"},
        ],
    }
    env = {"OPENCODE_ZEN_API_KEY": "sk-fake-opencode", "DEEPSEEK_API_KEY": "sk-fake-deepseek"}
    creds: dict = {}
    reg = _reg()
    build_registry(reg, config=cfg, env=env, credentials_out=creds)
    ids = [p.id for p in reg.list_providers()]
    assert "opencode" in ids and "deepseek" in ids and "claudehub" in ids
    oc = reg.get_provider("opencode")
    assert oc.metadata.get("primary") is True
    assert oc.defaultModel == "deepseek-v4-flash-free"
    ch = reg.get_provider("claudehub")
    assert ch.credentialConfigured is True
    nursing = reg.get_provider("nous")
    assert nursing.credentialConfigured is False   # no oauth in this env
    assert creds.get("opencode") == "sk-fake-opencode"
    assert creds.get("claudehub") == "sk-fake-custom"
    # initial classification per DoD
    or_ = reg.get_provider("openrouter")
    assert or_.healthStatus == ProviderHealthStatus.UNAVAILABLE
    assert or_.availabilityReason == AvailabilityReason.WAF_BLOCKED
    assert or_.routingEligible is False


# 16 ── events: scrubber masks secrets; retry policy is provider-aware
def test_events_scrubber_and_retry_policy():
    scrubbed = scrub({"provider": "x", "apiKey": "sk-secret",
                      "headers": {"Authorization": "Bearer zz"}})
    assert scrubbed["apiKey"] == "***"
    assert scrubbed["headers"]["Authorization"] == "***"
    assert scrubbed["provider"] == "x"

    rp = RetryPolicy(retryable=True, max_retries=3, backoff_base_s=0.25, backoff_max_s=2.0)
    assert rp.max_retries == 3
    assert rp.backoff(0) == 0.25
    assert rp.backoff(4) == 2.0                       # capped by backoff_max_s

    from agent.provider_registry.retry import DEFAULT_RETRY_POLICIES, RetryPolicyProvider
    provider = RetryPolicyProvider()
    assert provider.max_retries_for(ProviderErrorClass.NETWORK_TIMEOUT) == 2
    assert DEFAULT_RETRY_POLICIES[ProviderErrorClass.AUTH_INVALID].retryable is False
    assert DEFAULT_RETRY_POLICIES[ProviderErrorClass.WAF_BLOCKED].retryable is False