"""Sprint 1.2.0 — Controlled Intent Routing Enforcement tests (§15).

Covers the 15 mandatory tests plus the §3 mode-parsing fail-closed
rules and the §12 safety counters. Router-level tests never execute
tools; the adapter-level test (test_no_double_tool_execution) runs
the real enforce_event on a throwaway temp DB.
"""

import pytest

from agent.intent_router.classifier import Classification
from agent.intent_router.enforcement import (
    STATUS_READ_ALLOWLIST,
    status_read_allowlist_matches,
)
from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import (
    EnforcementBlockReason,
    ExpectedSideEffect,
    IntentRisk,
    IntentType,
    RouterMode,
)
from agent.intent_router.router import (
    IntentRouter,
    parse_mode,
    read_router_flags,
)


# ── helpers ─────────────────────────────────────────────────────────


def _router(health: str = "healthy", **flag_kw) -> IntentRouter:
    """Router in enforce_status_read mode with HEALTHY runtime."""
    flags = {"enabled": True,
             "mode": RouterMode.ENFORCE_STATUS_READ.value}
    flags.update(flag_kw)
    return IntentRouter(
        flags=flags,
        health_provider=lambda: {"status": health},
    )


def _enforce(router: IntentRouter, text: str, request_id: str = "t"):
    return router.enforce(
        features_from_text(text, request_id=request_id),
        text=text)


def _classification(intent, risk, side_effect, confidence,
                    reason_codes=None, lexical_hits=None):
    return Classification(
        intent=intent,
        risk=risk,
        expected_side_effect=side_effect,
        confidence=confidence,
        reason_codes=reason_codes or ["stub"],
        lexical_hits=lexical_hits or ["stub"],
    )


def _stub_router(classification: Classification,
                 health: str = "healthy") -> IntentRouter:
    class StubClassifier:
        VERSION = "stub"

        def classify(self, features) -> Classification:
            return classification

    return IntentRouter(
        classifier=StubClassifier(),
        flags={"enabled": True,
               "mode": RouterMode.ENFORCE_STATUS_READ.value},
        health_provider=lambda: {"status": health},
    )


# ── §3 mode parsing (fail closed) ───────────────────────────────────


def test_parse_mode_enforce_status_read():
    assert parse_mode("enforce_status_read") \
        is RouterMode.ENFORCE_STATUS_READ
    assert parse_mode("ENFORCE_STATUS_READ") \
        is RouterMode.ENFORCE_STATUS_READ


def test_parse_mode_fails_closed_on_unimplemented_and_garbage():
    # §3: only off/observe/enforce_status_read are allowed; any other
    # value fails closed to off.
    assert parse_mode("enforce") is RouterMode.OFF
    assert parse_mode("shadow_decision") is RouterMode.OFF
    assert parse_mode("banana") is RouterMode.OFF
    assert parse_mode(None) is RouterMode.OFF
    assert parse_mode("") is RouterMode.OFF


def test_read_router_flags_enforce_status_read_env():
    flags = read_router_flags({
        "HERMES_INTENT_ROUTER_ENABLED": "true",
        "HERMES_INTENT_ROUTER_MODE": "enforce_status_read",
    })
    assert flags["enabled"] is True
    assert flags["mode"] is RouterMode.ENFORCE_STATUS_READ


# ── §15 mandatory tests ─────────────────────────────────────────────


def test_status_read_can_route_v2():
    outcome = _enforce(_router(), "покажи статус Hermes")
    assert outcome is not None
    assert outcome.allowed is True
    assert outcome.actual_route == "V2_CANARY"
    assert outcome.block_reason is None
    # verified READ_ONLY surface only (§8) — write tools invisible.
    assert set(outcome.eligible_tools) == {
        "runtime_status", "canary_ping"}


def test_status_read_allowlist_matches_exact_phrases():
    # §7: the 5 allowlist phrases, word-boundary matched.
    assert status_read_allowlist_matches("покажи статус Hermes")
    assert status_read_allowlist_matches("статус gateway")
    assert status_read_allowlist_matches("состояние сервиса")
    assert status_read_allowlist_matches("health Hermes")
    assert status_read_allowlist_matches("gateway status")
    assert status_read_allowlist_matches(
        "покажи статус Hermes, пожалуйста")
    # non-allowlisted status phrasing must NOT match (no auto-expansion).
    assert not status_read_allowlist_matches("какой статус у процесса nginx")
    assert not status_read_allowlist_matches("найди статус последнего деплоя")
    assert not status_read_allowlist_matches("")
    # Sprint 1.2.1 §6: allowlist expanded (5 baseline + 8 RU + 7 EN,
    # minus 2 duplicate overlaps = 19 unique phrases).
    assert len(STATUS_READ_ALLOWLIST) == 19


def test_search_read_stays_legacy():
    # Sprint 1.2.1 §9/§10: SEARCH_READ is shadow-only — classified and
    # a candidate decision is BUILT, but the actual route is ALWAYS
    # LEGACY (block reason SEARCH_SHADOW_ONLY, never INTENT_NOT_ALLOWED).
    outcome = _enforce(_router(), "найди статус последнего деплоя")
    assert outcome is not None and outcome.allowed is False
    assert outcome.actual_route == "LEGACY"
    assert outcome.search_shadow is True
    assert outcome.block_reason == \
        EnforcementBlockReason.SEARCH_SHADOW_ONLY.value


def test_conversation_stays_legacy():
    outcome = _enforce(_router(), "привет")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.INTENT_NOT_ALLOWED.value


def test_write_stays_legacy():
    outcome = _enforce(_router(), "отправь сообщение")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.INTENT_NOT_ALLOWED.value


def test_delete_stays_legacy():
    outcome = _enforce(_router(), "удали лог")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.INTENT_NOT_ALLOWED.value


def test_system_stays_legacy():
    outcome = _enforce(_router(), "перезапусти gateway")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.INTENT_NOT_ALLOWED.value


def test_schedule_stays_legacy():
    outcome = _enforce(_router(), "каждый час проверяй статус")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.INTENT_NOT_ALLOWED.value


def test_unknown_stays_legacy():
    outcome = _enforce(_router(), "сделай это")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.INTENT_NOT_ALLOWED.value


def test_low_confidence_stays_legacy():
    # STATUS_READ intent but confidence below the 0.7 threshold.
    low = _classification(
        IntentType.STATUS_READ, IntentRisk.LOW,
        ExpectedSideEffect.READ_ONLY, 0.3,
    )
    outcome = _enforce(_stub_router(low), "покажи статус Hermes")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.LOW_CONFIDENCE.value


def test_unhealthy_runtime_stays_legacy():
    outcome = _enforce(_router(health="unhealthy"),
                       "покажи статус Hermes")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.HEALTH.value


def test_unknown_health_stays_legacy():
    # fail closed: unknown health is NOT healthy (§6).
    outcome = _enforce(_router(health="unknown"),
                       "покажи статус Hermes")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.HEALTH.value


def test_missing_capability_stays_legacy():
    from agent.intent_router.capabilities import CapabilityRegistry

    caps = CapabilityRegistry(
        capabilities={"UNVERIFIED_READ": "not the verified surface"})
    # READ_RUNTIME_STATUS is absent → STATUS_READ cannot be satisfied.
    router = IntentRouter(
        flags={"enabled": True,
               "mode": RouterMode.ENFORCE_STATUS_READ.value},
        capabilities=caps,
        health_provider=lambda: {"status": "healthy"},
    )
    outcome = _enforce(router, "покажи статус Hermes")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.CAPABILITY.value


def test_not_allowlisted_stays_legacy():
    # status_read intent, healthy, capable — but NOT in the allowlist.
    outcome = _enforce(_router(), "какой статус у процесса nginx")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.ALLOWLIST.value


def test_router_error_stays_legacy():
    class BoomClassifier:
        VERSION = "boom"

        def classify(self, features):
            raise RuntimeError("boom")

    router = IntentRouter(
        classifier=BoomClassifier(),
        flags={"enabled": True,
               "mode": RouterMode.ENFORCE_STATUS_READ.value},
        health_provider=lambda: {"status": "healthy"},
    )
    outcome = _enforce(router, "покажи статус Hermes")
    assert outcome is not None and outcome.allowed is False
    assert outcome.actual_route == "LEGACY"
    assert outcome.block_reason == \
        EnforcementBlockReason.ROUTER_ERROR.value
    stats = router.stats()["enforcement"]
    assert stats["failure"] == 1
    assert stats["blocks"]["ROUTER_ERROR"] == 1


def test_exactly_one_response():
    # One enforce() call emits EXACTLY ONE evaluation event for the
    # request — the gateway contract (§9) at the router level.
    router = _router()
    outcome = _enforce(router, "покажи статус Hermes", request_id="r1")
    assert outcome is not None and outcome.allowed
    events = [e for e in router.recent_events(50)
              if e.payload.get("request_id") == "r1"]
    assert len(events) == 1
    assert events[0].payload["actual_route"] == "V2_CANARY"


def test_no_double_tool_execution():
    # Adapter-level: one enforce run with ONE step → exactly one
    # TOOL_STARTED in the journal (counted from the journal, §19).
    from agent.gateway_v2.adapter import GatewayV2Adapter
    from agent.gateway_v2.flags import FeatureFlags

    class Evt:
        id = "evt-enforce-1"
        user_id = ""
        session_id = "s1"
        text = "покажи статус Hermes"
        metadata = {}

    adapter = GatewayV2Adapter(flags=FeatureFlags(
        enabled=True, persistence=True))
    resp = adapter.enforce_event(
        Evt(),
        step_specs=[{"name": "s1", "tool": "runtime_status"}],
    )
    assert resp.get("ok") is True
    assert resp.get("tool_calls") == 1  # exactly one, no duplicate
    # §30 invariant: after TOOL_STARTED exists, legacy fallback is
    # FORBIDDEN — a completed tool run reports fallback_allowed=False.
    assert resp.get("fallback_allowed") is False


def test_no_double_tool_execution_write_tool_impossible():
    # Write tools are IMPOSSIBLE in the enforced surface: an unknown/
    # write tool in step_specs → INVALID_PLAN → ZERO tool starts.
    from agent.gateway_v2.adapter import GatewayV2Adapter
    from agent.gateway_v2.flags import FeatureFlags

    class Evt:
        id = "evt-enforce-2"
        user_id = ""
        session_id = "s2"
        text = "покажи статус Hermes"
        metadata = {}

    adapter = GatewayV2Adapter(flags=FeatureFlags(
        enabled=True, persistence=True))
    resp = adapter.enforce_event(
        Evt(),
        step_specs=[{"name": "s1", "tool": "send_message"}],
    )
    assert resp.get("ok") is False
    assert resp.get("tool_calls") == 0


# ── §12 safety metrics ──────────────────────────────────────────────


def test_unsafe_intent_never_enforced_even_with_none_side_effect():
    # An unsafe intent claiming expected_side_effect=NONE must be
    # blocked by the INTENT gate FIRST (proven disposition precedence,
    # Sprint 1.1.1.1) and counted in the §12 safety metric.
    write_as_none = _classification(
        IntentType.WRITE_ACTION, IntentRisk.MEDIUM,
        ExpectedSideEffect.NONE, 0.95,
    )
    router = _stub_router(write_as_none)
    outcome = _enforce(router, "покажи статус Hermes")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == \
        EnforcementBlockReason.INTENT_NOT_ALLOWED.value
    stats = router.stats()["enforcement"]
    assert stats["unsafe"] == 1  # §12: unsafe seen at enforcement entry
    assert stats["allowed"] == 0
    assert stats["blocked"] == 1


def test_safety_counters_after_controlled_run():
    router = _router()
    _enforce(router, "покажи статус Hermes")
    _enforce(router, "привет")
    _enforce(router, "удали лог")
    stats = router.stats()["enforcement"]
    assert stats["attempts"] == 3
    assert stats["allowed"] == 1
    assert stats["blocked"] == 2
    assert stats["unsafe"] == 1  # only delete_action is an unsafe family
    assert stats["success"] == 0  # router-level: execution not run
    assert stats["fallback"] == 0
    assert stats["failure"] == 0


def test_record_enforcement_execution_updates_counters():
    router = _router()
    outcome = _enforce(router, "покажи статус Hermes")
    router.record_enforcement_execution(outcome, ok=True)
    router.record_enforcement_execution(outcome, ok=False, fell_back=True)
    stats = router.stats()["enforcement"]
    assert stats["success"] == 1
    assert stats["fallback"] == 1


def test_enforcement_inactive_outside_enforce_mode():
    # Mode != enforce_status_read → enforce() returns None (inert).
    for mode in (RouterMode.OFF, RouterMode.OBSERVE):
        router = IntentRouter(
            flags={"enabled": True, "mode": mode.value},
            health_provider=lambda: {"status": "healthy"},
        )
        assert router.enforce(
            features_from_text("покажи статус Hermes")) is None


def test_health_unhealthy_when_unsafe_enforced():
    router = _stub_router(_classification(
        IntentType.DELETE_ACTION, IntentRisk.CRITICAL,
        ExpectedSideEffect.IRREVERSIBLE_WRITE, 0.9,
    ))
    _enforce(router, "удали лог")
    health = router.health()
    assert health["level"] == "UNHEALTHY"  # §12 trigger
    assert health["enforcement"]["unsafe"] == 1


def test_pid_health_parses_json_and_plain_pid_file():
    # Sprint 1.2.0 activation fix: the gateway writes gateway.pid as a
    # JSON record; _pid_health must accept BOTH formats and fail closed
    # (None → unknown → HEALTH block → LEGACY) on garbage.
    from agent.intent_router import gateway_hook as gh

    assert gh._parse_pid_file('{"pid": 143116, "kind": "x"}') == 143116
    assert gh._parse_pid_file("143116") == 143116
    assert gh._parse_pid_file("  70538  ") == 70538
    assert gh._parse_pid_file("") is None
    assert gh._parse_pid_file('{"pid": "abc"}') is None
    assert gh._parse_pid_file("not-a-number") is None
    assert gh._parse_pid_file(None) is None
    # end-to-end: healthy when the pid file parses and the pid is alive
    import os

    import hermes_constants

    pid = os.getpid()
    tmp = None
    try:
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="v2-pidhealth-"))
        (tmp / "gateway.pid").write_text(
            f'{{"pid": {pid}, "kind": "test"}}')
        import unittest.mock as um

        with um.patch.object(hermes_constants, "get_hermes_home",
                             return_value=tmp):
            assert gh._pid_health() == {"status": "healthy"}
        (tmp / "gateway.pid").write_text("99999999")
        with um.patch.object(hermes_constants, "get_hermes_home",
                             return_value=tmp):
            # dead pid → kill(0) raises → unknown (fail closed)
            assert gh._pid_health() == {"status": "unknown"}
    finally:
        import shutil

        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
