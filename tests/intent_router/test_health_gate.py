"""Health gate tests (Sprint 1.1 §32-33, §61)."""

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.router import IntentRouter


def _router(health_status):
    return IntentRouter(
        flags={"enabled": True, "mode": "observe",
               "canary": True, "shadow": True},
        health_provider=lambda: {"status": health_status},
    )


def test_healthy_internal_read_canary():
    r = _router("healthy")
    d = r.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert d.effective_route == "v2_canary"


def test_degraded_no_effective_canary():
    r = _router("degraded")
    d = r.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert d.effective_route == "legacy"
    assert "health_gate" in d.reason_codes


def test_unhealthy_legacy():
    r = _router("unhealthy")
    d = r.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert d.effective_route == "legacy"
    assert d.candidate_route == "legacy"


def test_unknown_health_blocks_canary():
    r = _router("unknown")
    d = r.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert d.effective_route == "legacy"


def test_health_cache_reused():
    calls = []

    def provider():
        calls.append(1)
        return {"status": "healthy"}

    r = IntentRouter(
        flags={"enabled": True, "mode": "observe",
               "canary": True, "shadow": True},
        health_provider=provider,
    )
    for _ in range(5):
        r.observe(features_from_text("покажи статус", "r", internal=True))
    assert len(calls) == 1  # cached, not per-request
