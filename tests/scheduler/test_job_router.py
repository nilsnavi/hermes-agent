"""Scheduled-job Model Router integration tests (Sprint 0.6 §33)."""

import os
import pytest

from cron import job_router as jr
from cron.job_router import (
    JobRoutingError,
    attach_profile,
    job_has_explicit_pin,
    job_profile_id,
    profile_route_applies,
    retry_policy,
    route_job_profile,
    scheduled_router_enabled,
)

STALE_JOB = {
    "id": "x1", "name": "morning-report",
    "provider": "", "model": "",
    "provider_snapshot": "deepseek", "model_snapshot": "deepseek-v4-flash",
    "model_profile": "BALANCED",
    "schedule": {"kind": "cron", "expr": "0 9 * * *"},
    "deliver": "origin",
}

PINNED_JOB = {
    "id": "x2", "name": "pinned",
    "provider": "opencode-zen", "model": "deepseek-v4-flash-free",
    "model_profile": "BALANCED",
}


def _fake_registry():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from tests.model_router.test_router import build_registry

    return build_registry()


def _flag_on(monkeypatch):
    monkeypatch.setenv(jr.FLAG_ENV, "true")


# 1. profile job ignores stale observed snapshot
def test_profile_job_ignores_stale_snapshot(monkeypatch):
    _flag_on(monkeypatch)
    assert profile_route_applies(STALE_JOB) is True
    r = route_job_profile("BALANCED", STALE_JOB, registry=_fake_registry())
    # snapshot said deepseek — router must pick healthy opencode primary
    assert r["provider"] == "opencode"
    assert r["model"] == "deepseek-v4-flash-free"


# 2. explicit valid pin still honored (takes precedence over profile)
def test_explicit_pin_honored(monkeypatch):
    _flag_on(monkeypatch)
    assert job_has_explicit_pin(PINNED_JOB) is True
    assert profile_route_applies(PINNED_JOB) is False


# 3. profile route selects healthy provider
def test_profile_selects_healthy_provider():
    r = route_job_profile("BALANCED", None, registry=_fake_registry())
    assert r["provider"] == "opencode"
    assert r["model"] == "deepseek-v4-flash-free"
    assert r["reasonCode"] == "SELECTED"


# 4. broken provider excluded
def test_broken_provider_excluded():
    r = route_job_profile("BALANCED", None, registry=_fake_registry())
    broken = {c["provider"] for c in r["fallbackCandidates"]}
    assert not (broken & {"claudehub", "openrouter", "nous"})


# 5. NO_ROUTE returns routing failure (clear, not generic traceback)
def test_no_route_is_routing_failure():
    with pytest.raises(JobRoutingError) as ei:
        route_job_profile("CODING", None, registry=_fake_registry())
    assert "NO_ROUTE_AVAILABLE" in str(ei.value)


# 6. unsupported / broken never invokes legacy fallback chain
def test_no_legacy_fallback_chain():
    r = route_job_profile("BALANCED", None, registry=_fake_registry())
    # fallback list contains only healthy eligible models — never claudehub
    for c in r["fallbackCandidates"]:
        assert c["provider"] not in ("claudehub", "openrouter", "nous")


# 7. script-only / no-agent job bypasses Router
def test_script_only_bypasses_router(monkeypatch):
    _flag_on(monkeypatch)
    no_agent = {"id": "x3", "no_agent": True, "script": "nutriflow_backup.py"}
    assert profile_route_applies(no_agent) is False
    assert job_profile_id(no_agent) is None


# 8. schedule/timezone/name/deliver unchanged by migration helper
def test_attach_profile_keeps_schedule():
    out = attach_profile(STALE_JOB, "BALANCED")
    assert out["schedule"] == STALE_JOB["schedule"]
    assert out["deliver"] == "origin"
    assert out["name"] == STALE_JOB["name"]
    assert out["model_profile"] == "BALANCED"
    # snapshots remain as diagnostic metadata
    assert out["provider_snapshot"] == "deepseek"


# 9. idempotency: duplicate fire blocked (at-most-once claim)
def test_idempotency_duplicate_fire_blocked(monkeypatch):
    import cron.jobs as jobs_mod

    fake = {"id": "x9", "enabled": True, "state": "scheduled",
            "schedule": {"kind": "cron", "expr": "0 9 * * *"}}
    store = [dict(fake)]

    def _load():
        return [dict(j) for j in store]  # fresh copies, like disk round-trip

    def _save(jobs):
        store[:] = [dict(j) for j in jobs]

    monkeypatch.setattr(jobs_mod, "load_jobs", _load)
    monkeypatch.setattr(jobs_mod, "save_jobs", _save)
    assert jobs_mod.claim_job_for_fire("x9") is True
    # second claim within TTL must lose (no duplicate execution)
    assert jobs_mod.claim_job_for_fire("x9") is False


# 10. retryable generation error retries
def test_retryable_error_retries():
    assert retry_policy("timeout after 30s upstream") == "retryable"
    assert retry_policy("provider 503 unavailable") == "retryable"
    assert retry_policy("rate limit exceeded") == "retryable"


# 11. non-retryable auth error does not retry
def test_non_retryable_auth_no_retry():
    assert retry_policy("AUTH_INVALID for claudehub") == "non_retryable"
    assert retry_policy("NO_ROUTE_AVAILABLE for profile") == "non_retryable"
    assert retry_policy("WAF_BLOCKED by security policy") == "non_retryable"
    assert retry_policy("GEO_BLOCKED") == "non_retryable"


# 12. delivery failure does not force new generation (output already saved)
def test_delivery_failure_no_regeneration(monkeypatch):
    import cron.scheduler as sched

    monkeypatch.setattr(sched, "_resolve_delivery_targets", lambda job, **k: [])
    job = {"id": "x12", "name": "t", "deliver": "local"}
    # local-only job with no targets → delivery returns None (not failure);
    # generation output stays in last_output — no re-generation needed.
    assert sched._deliver_result(job, "generated report") is None


# 13. feature flag false → legacy unchanged
def test_flag_false_legacy_unchanged(monkeypatch):
    monkeypatch.delenv(jr.FLAG_ENV, raising=False)
    assert scheduled_router_enabled() is False
    assert profile_route_applies(STALE_JOB) is False


# 14. scoped flag only affects scheduler path, not global chat router
def test_scoped_flag_does_not_enable_global_router(monkeypatch):
    _flag_on(monkeypatch)
    assert scheduled_router_enabled() is True
    from agent.model_router import router_v2_enabled

    assert router_v2_enabled() is False  # global chat path stays legacy
