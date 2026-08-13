"""Sprint 1.1.1 observe-calibration tests (§28-30, §40, §6, §9-14).

Covers the hard safety rule (actual route never depends on the router),
error isolation, safe telemetry schema, sample-source/actual-route
enums, metrics and health, and the mode guard (ENFORCE/SHADOW_DECISION
fail closed to OFF).
"""

import os
from unittest.mock import patch

import pytest

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.gateway_hook import (
    actual_route_from_v2,
    observe_gateway_event,
)
from agent.intent_router.models import ActualRoute, SampleSource
from agent.intent_router.router import IntentRouter, read_router_flags

_SECRET_MARKER = "sk-verysecret-token-1234567890abcdef"


def _hook_router(monkeypatch, flags=None):
    """Router isolated from process-wide state for hook tests."""
    r = IntentRouter(
        flags=flags or {"enabled": True, "mode": "observe",
                        "canary": False, "shadow": False},
        health_provider=lambda: {"status": "healthy"},
    )
    monkeypatch.setattr(
        "agent.intent_router.gateway_hook._get_router", lambda: r)
    return r


# ── §6 mode guard ────────────────────────────────────────────────────


@pytest.mark.parametrize("bad_mode", ["enforce", "shadow_decision"])
def test_mode_guard_fails_closed_to_off(bad_mode):
    """§6: ENFORCE / SHADOW_DECISION in env must downgrade to OFF."""
    flags = read_router_flags({
        "HERMES_INTENT_ROUTER_ENABLED": "true",
        "HERMES_INTENT_ROUTER_MODE": bad_mode,
    })
    assert flags["enabled"] is True
    assert flags["mode"].value == "off"


def test_parse_mode_garbage_is_off():
    from agent.intent_router.router import parse_mode

    assert parse_mode("bogus").value == "off"
    assert parse_mode("").value == "off"
    assert parse_mode(None).value == "off"


# ── §7 hook contract / disabled ──────────────────────────────────────


def test_router_disabled_not_called(monkeypatch):
    """§40 test_router_disabled_not_called: flags off → hook inert."""
    calls = {"n": 0}

    def _spy(*a, **kw):
        calls["n"] += 1
        return None

    monkeypatch.setenv("HERMES_INTENT_ROUTER_ENABLED", "false")
    monkeypatch.setenv("HERMES_INTENT_ROUTER_MODE", "observe")
    monkeypatch.setattr(
        "agent.intent_router.gateway_hook._get_router", _spy)
    assert observe_gateway_event("покажи статус", "r1") is None
    assert calls["n"] == 0


def test_observe_mode_required(monkeypatch):
    """enabled=true but mode=off → hook inert (no router call)."""
    calls = {"n": 0}

    def _spy(*a, **kw):
        calls["n"] += 1
        return None

    monkeypatch.setenv("HERMES_INTENT_ROUTER_ENABLED", "true")
    monkeypatch.setenv("HERMES_INTENT_ROUTER_MODE", "off")
    monkeypatch.setattr(
        "agent.intent_router.gateway_hook._get_router", _spy)
    assert observe_gateway_event("покажи статус", "r1") is None
    assert calls["n"] == 0


# ── §28-30 equivalence / authority ───────────────────────────────────


def test_observe_actual_route_unchanged():
    """§28: observing must not change the effective route."""
    r = IntentRouter(
        flags={"enabled": True, "mode": "observe",
               "canary": False, "shadow": False},
        health_provider=lambda: {"status": "healthy"},
    )
    d = r.observe(features_from_text(
        "покажи статус сервера", "r1"), actual_route="LEGACY")
    # production observe has canary/shadow flags off → legacy effective
    assert d.effective_route == "legacy"
    assert d.actual_route == "LEGACY"
    assert d.matched is True


def test_observe_response_unchanged():
    """Input text/features are never mutated by the router."""
    text = "покажи статус сервера"
    r = IntentRouter(
        flags={"enabled": True, "mode": "observe"},
        health_provider=lambda: {"status": "healthy"},
    )
    feats = features_from_text(text, "r1")
    before = feats.to_dict()
    r.observe(feats, actual_route="LEGACY")
    assert feats.to_dict() == before
    assert feats.lexical_hits  # features intact


def test_observe_tool_calls_unchanged():
    """§30: router has no execution surface at all."""
    r = IntentRouter(flags={"enabled": True, "mode": "observe"})
    for attr in ("execute", "run", "resume", "decide_gateway",
                 "modify_request"):
        assert not hasattr(r, attr), f"router must not expose {attr}"
    # no provider/network imports are reachable from the observe path
    d = r.observe(features_from_text("привет", "r1"),
                  actual_route="LEGACY")
    assert d.effective_route in ("legacy", "v2_canary", "v2_shadow")


def test_router_exception_isolated(monkeypatch):
    """§8: classifier exception → fail-closed decision, never raises,
    error counter incremented, request proceeds normally."""
    from agent.intent_router.classifier import IntentClassifier

    class Boom(IntentClassifier):
        def classify(self, features):
            raise RuntimeError("boom")

    r = _hook_router(monkeypatch)
    r._classifier = Boom()
    monkeypatch.setenv("HERMES_INTENT_ROUTER_ENABLED", "true")
    monkeypatch.setenv("HERMES_INTENT_ROUTER_MODE", "observe")
    result = observe_gateway_event("удали файл", "r-boom")
    # fail-closed fallback decision, no exception propagates
    assert result is not None
    assert result.effective_route == "legacy"
    assert result.reason_codes == ["router_error"]
    assert r.stats()["errors"] == 1


# ── §9-10 telemetry schema / sample source ───────────────────────────


def test_telemetry_no_prompt(monkeypatch):
    """§9/§31: raw prompt never enters the event payload or log."""
    import logging

    records = []
    handler = logging.Handler()
    handler.emit = lambda rec: records.append(rec.getMessage())
    logger = logging.getLogger("gateway.intent_router")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        r = _hook_router(monkeypatch)
        monkeypatch.setenv("HERMES_INTENT_ROUTER_ENABLED", "true")
        monkeypatch.setenv("HERMES_INTENT_ROUTER_MODE", "observe")
        d = observe_gateway_event(
            f"удали файл {_SECRET_MARKER}", "r-secret",
            actual_route="LEGACY")
        assert d is not None
        payload = r.recent_events(1)[-1].payload
        joined = str(payload) + "\n".join(records)
        assert _SECRET_MARKER not in joined
        assert "удали файл" not in str(payload)
    finally:
        logger.removeHandler(handler)


def test_telemetry_no_secret(monkeypatch):
    """§31: Authorization/cookie/token-like strings never persisted."""
    r = _hook_router(monkeypatch)
    monkeypatch.setenv("HERMES_INTENT_ROUTER_ENABLED", "true")
    monkeypatch.setenv("HERMES_INTENT_ROUTER_MODE", "observe")
    d = observe_gateway_event(
        f"покажи статус Authorization: Bearer {_SECRET_MARKER}",
        "r-auth", actual_route="LEGACY")
    assert d is not None
    payload = r.recent_events(1)[-1].payload
    assert _SECRET_MARKER not in str(payload)


def test_event_payload_whitelist(monkeypatch):
    """§9: payload carries exactly the whitelisted scalars/counts."""
    r = _hook_router(monkeypatch)
    monkeypatch.setenv("HERMES_INTENT_ROUTER_ENABLED", "true")
    monkeypatch.setenv("HERMES_INTENT_ROUTER_MODE", "observe")
    d = observe_gateway_event(
        "покажи статус Hermes", "r-wl", actual_route="LEGACY",
        sample_source="LIVE")
    assert d is not None
    payload = r.recent_events(1)[-1].payload
    for key in ("request_id", "intent", "risk", "expected_side_effect",
                "candidate_route", "effective_route", "actual_route",
                "confidence_bucket", "reason_codes",
                "required_capability_count", "missing_capability_count",
                "matched", "router_version", "policy_version",
                "duration_ms", "sample_source", "mode"):
        assert key in payload, f"missing whitelisted field {key}"
    assert payload["actual_route"] == "LEGACY"
    assert payload["sample_source"] == "LIVE"
    assert payload["required_capability_count"] == len(
        d.required_capabilities)
    assert payload["missing_capability_count"] == len(
        d.missing_capabilities)


def test_sample_source_enum_values():
    assert [s.value for s in SampleSource] == [
        "LIVE", "INTERNAL_SYNTHETIC", "EXPLICIT_CANARY", "EXPLICIT_SHADOW",
    ]


def test_sample_source_propagates(monkeypatch):
    r = _hook_router(monkeypatch)
    monkeypatch.setenv("HERMES_INTENT_ROUTER_ENABLED", "true")
    monkeypatch.setenv("HERMES_INTENT_ROUTER_MODE", "observe")
    d = observe_gateway_event(
        "проверь статус", "r-ss", sample_source="INTERNAL_SYNTHETIC")
    assert d.sample_source == "INTERNAL_SYNTHETIC"
    assert r.recent_events(1)[-1].payload["sample_source"] == \
        "INTERNAL_SYNTHETIC"


# ── §11 actual route enum ────────────────────────────────────────────


def test_actual_route_enum_values():
    assert [a.value for a in ActualRoute] == [
        "LEGACY", "V2_CANARY", "SHADOW", "OPERATIONS", "OTHER",
    ]


def test_actual_route_from_v2():
    class D:
        def __init__(self, v):
            self.value = v

    assert actual_route_from_v2(D("legacy")) == "LEGACY"
    assert actual_route_from_v2(D("v2_canary")) == "V2_CANARY"
    assert actual_route_from_v2(D("shadow")) == "SHADOW"
    assert actual_route_from_v2(None) == "LEGACY"
    assert actual_route_from_v2(D("legacy"), internal=True) == "OPERATIONS"


def test_actual_route_never_inferred_from_text():
    """§11: actual route comes from routing state, not response text."""
    r = IntentRouter(flags={"enabled": True, "mode": "observe"},
                     health_provider=lambda: {"status": "healthy"})
    d = r.observe(features_from_text("покажи статус", "r1"),
                  actual_route="SHADOW")
    assert d.actual_route == "SHADOW"  # from state, text says nothing


# ── §12-13 metrics ───────────────────────────────────────────────────


def test_router_metrics(monkeypatch):
    """§12-13: router-level counters (matches/mismatches/recommended/
    actual) are deterministic per router instance."""
    r = _hook_router(monkeypatch)
    monkeypatch.setenv("HERMES_INTENT_ROUTER_ENABLED", "true")
    monkeypatch.setenv("HERMES_INTENT_ROUTER_MODE", "observe")
    observe_gateway_event("покажи статус", "m1", actual_route="LEGACY")
    observe_gateway_event("удали файл", "m2", actual_route="LEGACY")
    s = r.stats()
    assert s["decisions"] == 2
    assert s["errors"] == 0
    assert s["matches"] == 1              # status → legacy matched
    assert s["policy_mismatches"] == 1    # delete → deny vs legacy
    assert s["recommended"]["legacy"] == 1
    assert s["recommended"]["deny"] == 1
    assert s["actual"]["legacy"] == 2
    # process-wide observation counter is additive across tests
    from agent.intent_router.gateway_hook import observe_metrics
    before = observe_metrics()["router_observations_total"]
    observe_gateway_event("привет", "m3", actual_route="LEGACY")
    assert observe_metrics()["router_observations_total"] == before + 1


def test_unsafe_never_recommends_canary():
    """§13: WRITE/DELETE/SYSTEM/UNKNOWN never get a canary candidate."""
    r = IntentRouter(
        flags={"enabled": True, "mode": "observe",
               "canary": True, "shadow": True},
        health_provider=lambda: {"status": "healthy"},
    )
    for text in ("удали файл", "отправь сообщение",
                 "перезапусти gateway", "сделай это"):
        d = r.observe(features_from_text(text, "u"))
        assert d.candidate_route not in ("v2_canary", "v2_shadow"), text
    assert r.stats()["unsafe_predictions"] == 0
    assert r.stats()["unsafe_predicted_read_only"] == 0


# ── §14 health ───────────────────────────────────────────────────────


def test_router_health(monkeypatch):
    r = _hook_router(monkeypatch)
    monkeypatch.setenv("HERMES_INTENT_ROUTER_ENABLED", "true")
    monkeypatch.setenv("HERMES_INTENT_ROUTER_MODE", "observe")
    for i in range(50):
        observe_gateway_event("покажи статус", f"h{i}",
                              actual_route="LEGACY")
    h = r.health()
    for key in ("level", "enabled", "mode", "observations", "errors",
                "error_rate", "unsafe_canary_recommendations",
                "unsafe_predicted_read_only", "p50_ms", "p95_ms"):
        assert key in h, f"missing health field {key}"
    assert h["enabled"] is True
    assert h["mode"] == "observe"
    assert h["observations"] == 50
    assert h["errors"] == 0
    assert h["unsafe_canary_recommendations"] == 0
    assert h["unsafe_predicted_read_only"] == 0
    assert h["level"] == "HEALTHY"
    assert h["p50_ms"] is not None and h["p95_ms"] is not None


def test_health_unhealthy_on_unsafe():
    r = IntentRouter(flags={"enabled": True, "mode": "observe"},
                     health_provider=lambda: {"status": "healthy"})
    r._stats.unsafe_predictions = 1
    assert r.health()["level"] == "UNHEALTHY"


# ── §32 config writer regression ─────────────────────────────────────


def test_config_writer_preserves_sections_on_flag_update(tmp_path):
    """§32/§40: a single-section flag update must preserve all other
    config sections. Mirrors the dashboard flow
    (web_server.py: save_config(_deep_merge(existing, incoming))):
    merge-then-save keeps fallback_providers, mcp_servers,
    channel_prompts, command_allowlist, sessions, plugins intact."""
    import yaml

    from hermes_cli.config import _deep_merge, load_config, save_config

    base = {
        "model": {"provider": "deepseek", "default": "deepseek-v4-flash"},
        "fallback_providers": [
            {"provider": "opencode-zen", "model": "deepseek-v4-flash-free"},
        ],
        "mcp_servers": {
            "firecrawl": {"command": "npx", "args": ["firecrawl-mcp"]},
        },
        "channel_prompts": {"telegram": {"prompt": "be concise"}},
        "command_allowlist": ["find -delete", "recursive delete"],
        "sessions": {"auto_prune": True, "retention_days": 90},
        "plugins": {"enabled": ["max-plugin"]},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(base, sort_keys=False), encoding="utf-8")

    with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path)}):
        existing = load_config()
        incoming = {"model": {"provider": "opencode-zen",
                              "default": "deepseek-v4-flash-free"}}
        save_config(_deep_merge(existing, incoming))
        saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert saved["model"]["provider"] == "opencode-zen"
        for section in ("fallback_providers", "mcp_servers",
                        "channel_prompts", "command_allowlist",
                        "sessions", "plugins"):
            assert saved[section] == base[section], section
