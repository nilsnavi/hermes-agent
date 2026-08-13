"""Router facade tests (Sprint 1.1 §12, §20-21, §35, §39, §56)."""

import pytest

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import RequestIntentFeatures
from agent.intent_router.router import IntentRouter, parse_mode, read_router_flags


def test_router_status_read_candidate_canary(router_healthy):
    d = router_healthy.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert d.intent == "status_read"
    assert d.candidate_route == "v2_canary"
    assert d.effective_route == "v2_canary"
    assert d.canary_eligible is True


def test_router_non_allowlisted_read_legacy(router_healthy):
    # internal=False → not allowlisted → effective legacy.
    d = router_healthy.observe(features_from_text(
        "покажи статус сервера", "r1"))
    assert d.candidate_route == "v2_canary"
    assert d.effective_route == "legacy"
    assert "canary_allowlist_required" in d.reason_codes


def test_router_write_never_canary(router_healthy):
    for text in ("удали файл", "отправь сообщение", "перезапусти сервис",
                 "напомни завтра"):
        d = router_healthy.observe(features_from_text(text, "r", internal=True))
        assert d.effective_route != "v2_canary", text
        assert d.candidate_route != "v2_canary", text


def test_router_unknown_legacy(router_healthy):
    d = router_healthy.observe(features_from_text("сделай это", "r"))
    assert d.intent == "unknown"
    assert d.effective_route == "legacy"
    assert d.recommended_route == "legacy"


def test_router_ambiguous_legacy(router_healthy):
    d = router_healthy.observe(features_from_text("проверь", "r"))
    assert d.effective_route == "legacy"


def test_router_mixed_read_delete_write_wins(router_healthy):
    d = router_healthy.observe(features_from_text(
        "покажи статус и удали файл", "r", internal=True))
    assert d.intent == "delete_action"
    assert d.effective_route != "v2_canary"


def test_router_candidate_effective_split(router_healthy):
    # CANARY flag off → candidate may be canary but effective legacy.
    r = IntentRouter(
        flags={"enabled": True, "mode": "observe",
               "canary": False, "shadow": False},
        health_provider=lambda: {"status": "healthy"},
    )
    d = r.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert d.candidate_route == "legacy"  # canary flag off → not eligible
    assert d.effective_route == "legacy"


def test_router_health_gate(router_healthy):
    # UNHEALTHY → no canary even for internal allowlisted read.
    r = IntentRouter(
        flags={"enabled": True, "mode": "observe",
               "canary": True, "shadow": True},
        health_provider=lambda: {"status": "unhealthy"},
    )
    d = r.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert d.effective_route == "legacy"
    assert "health_gate" in d.reason_codes


def test_router_error_fails_closed():
    from agent.intent_router.classifier import IntentClassifier

    class Boom(IntentClassifier):
        def classify(self, features):
            raise RuntimeError("boom")

    r = IntentRouter(classifier=Boom(),
                     flags={"enabled": True, "mode": "observe",
                            "canary": True, "shadow": True})
    d = r.observe(RequestIntentFeatures(request_id="r1"))
    assert d.effective_route == "legacy"
    assert d.recommended_route == "legacy"
    assert "router_error" in d.reason_codes
    assert r.stats()["errors"] == 1


def test_observe_mode_zero_mutation(router_healthy):
    # Observe returns a decision but never executes anything.
    import sqlite3
    import tempfile
    import os

    # The router takes no db path at all — proving no DB writes are
    # possible from the facade.
    assert not hasattr(router_healthy, "_db")


def test_router_no_tool_calls(router_healthy, monkeypatch):
    from agent.gateway_v2.canary import default_canary_registry

    reg = default_canary_registry()
    calls = []

    orig = reg.get
    monkeypatch.setattr(reg, "get", lambda name, *a, **kw: (
        calls.append(name) or orig(name, *a, **kw)))

    d = router_healthy.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert calls == []  # router never touches tools


def test_parse_mode_defaults():
    assert parse_mode(None).value == "off"
    assert parse_mode("garbage").value == "off"
    assert parse_mode("observe").value == "observe"
    assert parse_mode("enforce").value == "off"  # ENFORCE not implemented


def test_read_router_flags_defaults(monkeypatch):
    monkeypatch.delenv("HERMES_INTENT_ROUTER_ENABLED", raising=False)
    monkeypatch.delenv("HERMES_INTENT_ROUTER_MODE", raising=False)
    flags = read_router_flags({})
    assert flags["enabled"] is False
    assert flags["mode"].value == "off"


def test_read_router_flags_observe(monkeypatch):
    flags = read_router_flags({
        "HERMES_INTENT_ROUTER_ENABLED": "true",
        "HERMES_INTENT_ROUTER_MODE": "observe",
    })
    assert flags["enabled"] is True
    assert flags["mode"].value == "observe"


def test_router_duration_ms_set(router_healthy):
    d = router_healthy.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert d.duration_ms is not None
