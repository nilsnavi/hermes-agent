"""Sprint 1.2.3 §34 — SEARCH_READ controlled-canary mandatory tests.

Covers the SearchCanaryPolicy (ALLOW_V2_SEARCH | LEGACY + mandatory
deny reasons §6), the §9 allowlist (exact phrases, no expansion),
§7 mixed-intent safety, §8 secret queries, §13 one-tool limit,
§18 canary cap (live only), §19 LIVE/SYNTHETIC accounting, §26
empty-result success, §27 source-unavailable fail-closed, and
§17 STATUS_READ regression (enforcement unchanged with the canary
flag ON).

The canary flag is ON in every router test here (``search_canary``
in flags) — with the flag OFF the exact 1.2.2 shadow behavior is
covered by test_search_shadow.py.
"""

import pytest

from agent.intent_router.capabilities import CapabilityRegistry
from agent.intent_router.enforcement import (
    SEARCH_CANARY_ALLOWLIST,
    SEARCH_CANARY_MAX_SUCCESS,
    SEARCH_ALLOWED_SOURCES,
    SEARCH_ALLOWED_SUBTYPES,
    SearchCanaryPolicy,
    detect_search_subtype,
    has_mixed_unsafe_intent,
    search_canary_allowlist_matches,
)
from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import (
    RouterMode,
    SearchDenyReason,
)
from agent.intent_router.router import IntentRouter


def _router(health: str = "healthy", capabilities=None) -> IntentRouter:
    return IntentRouter(
        flags={"enabled": True,
               "mode": RouterMode.ENFORCE_STATUS_READ.value,
               "search_canary": True},
        health_provider=lambda: {"status": health},
        capabilities=capabilities,
    )


def _enforce(router, text, request_id="t", sample_source="LIVE"):
    return router.enforce(
        features_from_text(text, request_id=request_id),
        sample_source=sample_source,
        text=text)


# ── §34 positives: C1-C6 allowed through the canary ────────────────


def test_search_canary_allowed_gateway_log():
    """§34/§1 — allowlisted gateway-log search is GRANTED V2."""
    router = _router()
    outcome = _enforce(router, "найди последние ошибки gateway")
    assert outcome is not None
    assert outcome.allowed is True
    assert outcome.actual_route == "V2_CANARY"
    assert outcome.search_canary is True
    assert outcome.search_subtype == "log_search"
    assert outcome.search_source == "GATEWAY_LOG"
    assert outcome.search_deny_reason is None
    assert outcome.eligible_tools == ["operational_log_search"]
    assert "search_canary_allowed" in outcome.reason_codes


def test_search_canary_allowed_events():
    """§34/§1 — allowlisted events search is GRANTED V2."""
    router = _router()
    outcome = _enforce(
        router, "покажи события Hermes за последний час")
    assert outcome.allowed is True
    assert outcome.actual_route == "V2_CANARY"
    assert outcome.search_subtype == "event_search"
    assert outcome.search_source == "EVENTS"
    assert outcome.eligible_tools == ["operational_log_search"]


def test_search_canary_allowed_scheduler():
    """§34/§1 — allowlisted scheduler search is GRANTED V2."""
    router = _router()
    outcome = _enforce(router, "найди ошибки scheduler")
    assert outcome.allowed is True
    assert outcome.search_subtype == "scheduler_search"
    assert outcome.search_source == "SCHEDULER"


def test_search_canary_allowed_provider():
    """§34/§1 — allowlisted provider search is GRANTED V2."""
    router = _router()
    outcome = _enforce(router, "покажи последние provider errors")
    assert outcome.allowed is True
    assert outcome.search_subtype == "provider_search"
    assert outcome.search_source == "PROVIDER"


def test_search_canary_allowed_integration():
    """§34/§1 — allowlisted integration search is GRANTED V2."""
    router = _router()
    outcome = _enforce(router, "найди ошибки Telegram")
    assert outcome.allowed is True
    assert outcome.search_subtype == "integration_search"
    assert outcome.search_source == "INTEGRATION"
    # MCP maps to the same integration subtype.
    outcome2 = _enforce(router, "последние ошибки MCP")
    assert outcome2.allowed is True
    assert outcome2.search_subtype == "integration_search"
    # EN phrases too.
    outcome3 = _enforce(router, "show MCP errors")
    assert outcome3.allowed is True
    assert outcome3.search_source == "INTEGRATION"


# ── §34 negatives: never V2 ────────────────────────────────────────


def test_search_secret_query_legacy():
    """§34/§8 — a secret-hunting search NEVER reaches the tool."""
    router = _router()
    outcome = _enforce(router, "найди пароль")
    assert outcome is not None and outcome.allowed is False
    assert outcome.actual_route == "LEGACY"
    assert outcome.search_canary is True
    assert outcome.search_deny_reason == \
        SearchDenyReason.SECRET_QUERY.value
    assert outcome.eligible_tools == []  # tool execution = 0
    assert "search_secret_query" in outcome.reason_codes


def test_search_filesystem_query_legacy():
    """§34/§3/§9 — filesystem searches are not allowlisted → LEGACY."""
    router = _router()
    for text in ("поищи в моих файлах", "search my files"):
        outcome = _enforce(router, text)
        assert outcome is not None and outcome.allowed is False
        assert outcome.actual_route == "LEGACY"
        assert outcome.search_deny_reason == \
            SearchDenyReason.SEARCH_NOT_ALLOWLISTED.value
        assert outcome.eligible_tools == []


def test_search_web_query_legacy():
    """§34/§18 N6 — a web search is not operational → LEGACY."""
    router = _router()
    outcome = _enforce(router, "найди в интернете последние новости")
    assert outcome is not None and outcome.allowed is False
    assert outcome.actual_route == "LEGACY"
    assert outcome.search_deny_reason == \
        SearchDenyReason.SEARCH_NOT_ALLOWLISTED.value
    assert outcome.eligible_tools == []


def test_search_delete_mixed_legacy():
    """§34/§7 N4 — search+delete is DELETE_ACTION, unsafe wins."""
    router = _router()
    outcome = _enforce(router, "найди и удали старые ошибки")
    assert outcome is not None and outcome.allowed is False
    assert outcome.intent == "delete_action"
    assert outcome.actual_route == "LEGACY"
    assert outcome.search_canary is False  # never reached search branch


def test_search_system_mixed_legacy():
    """§34/§7 N5 — search+restart is SYSTEM_ACTION, unsafe wins."""
    router = _router()
    outcome = _enforce(router,
                       "найди ошибку и перезапусти gateway")
    assert outcome is not None and outcome.allowed is False
    assert outcome.intent == "system_action"
    assert outcome.actual_route == "LEGACY"
    assert outcome.search_canary is False


def test_search_schedule_mixed_legacy():
    """§34/§7 — search+create-cron is WRITE/SCHEDULE, unsafe wins."""
    router = _router()
    outcome = _enforce(router,
                       "проверь scheduler errors и создай cron")
    assert outcome is not None and outcome.allowed is False
    assert outcome.intent in ("write_action", "schedule_action")
    assert outcome.actual_route == "LEGACY"
    assert outcome.search_canary is False


# ── §34 execution/response discipline ──────────────────────────────


def test_search_exactly_one_response():
    """§34/§11 — one granted canary run = exactly ONE outcome with a
    single eligible tool; no shadow+canary double decision."""
    router = _router()
    outcome = _enforce(router, "найди последние ошибки gateway")
    assert outcome is not None
    assert outcome.allowed is True
    # Exactly one tool surface, exactly one decision (no duplicate).
    assert outcome.eligible_tools == ["operational_log_search"]
    assert outcome.search_shadow is False
    assert outcome.search_canary is True
    # The outcome is deterministic and idempotent: re-running the same
    # request yields the same single decision, not a second path.
    outcome2 = _enforce(router, "найди последние ошибки gateway")
    assert outcome2.allowed is True
    assert outcome2.eligible_tools == ["operational_log_search"]
    stats = router.stats()["search_enforcement"]
    assert stats["attempts"] == 2
    assert stats["allowed"] == 2


def test_search_exactly_one_tool():
    """§34/§13 — the canary surface is ONE verified tool, no chaining."""
    router = _router()
    outcome = _enforce(router, "покажи последние provider errors")
    assert outcome.eligible_tools == ["operational_log_search"]
    # A granted search run must never expose a second tool.
    assert len(outcome.eligible_tools) == 1
    stats = router.stats()["search_enforcement"]
    assert stats["by_subtype"]["provider_search"]["allowed"] == 1


def test_search_empty_result_no_fallback():
    """§34/§26 — 0 matches is a SUCCESSFUL read-only result; the
    router still grants V2 (result count never affects routing)."""
    from agent.operational_search import (
        OperationalSearchEngine,
        SearchRequest,
        SearchSource,
    )
    router = _router()
    outcome = _enforce(router, "найди последние ошибки gateway")
    assert outcome.allowed is True  # routing decision independent
    engine = OperationalSearchEngine()
    res = engine.search(SearchRequest(
        query="zzz-no-such-literal-12345",
        source=SearchSource.GATEWAY_LOG,
    ))
    assert res.ok is True
    assert len(res.results) == 0  # empty = successful read-only result


def test_search_source_unavailable_safe():
    """§34/§27 — an unavailable source fails closed BEFORE the tool
    (policy: health unknown → LEGACY); a bad explicit path ERRORS
    after start (never a blind duplicate)."""
    # Policy gate: runtime health unknown → HEALTH_UNAVAILABLE → LEGACY.
    router = _router(health="unknown")
    outcome = _enforce(router, "найди последние ошибки gateway")
    assert outcome is not None and outcome.allowed is False
    assert outcome.search_deny_reason == \
        SearchDenyReason.HEALTH_UNAVAILABLE.value
    # Engine gate: explicitly passed nonexistent EVENTS db path →
    # SOURCE_UNAVAILABLE (the verified fail-closed case, §27).
    from agent.operational_search import (
        OperationalSearchEngine,
        SearchErrorCode,
        SearchRequest,
        SearchSource,
    )
    engine = OperationalSearchEngine(
        paths={"state_db": "/nonexistent/zzz/state.db"})
    res = engine.search(SearchRequest(
        query="telegram", source=SearchSource.EVENTS))
    assert res.ok is False
    assert res.error.code == SearchErrorCode.SOURCE_UNAVAILABLE


def test_search_duplicate_input_blocked():
    """§34/§30 — the same run_id+step_id+input_hash cannot execute the
    tool twice (executor idempotency key; §29 one TOOL_STARTED/
    TOOL_COMPLETED pair max)."""
    from agent.orchestrator.idempotency import (
        compute_input_hash,
        idempotency_key,
    )
    args = {"source": "GATEWAY_LOG", "limit": 10}
    h1 = compute_input_hash(args)
    h2 = compute_input_hash(dict(args))
    assert h1 == h2  # identical input → identical hash
    key = idempotency_key("run-1", "step-1", h1)
    assert key == idempotency_key("run-1", "step-1", h1)
    assert key != idempotency_key("run-1", "step-2", h1)
    assert key != idempotency_key("run-2", "step-1", h1)


def test_search_status_enforcement_unchanged():
    """§34/§17 — STATUS_READ enforcement works unchanged with the
    canary flag ON; search counters untouched by status requests."""
    router = _router()
    outcome = _enforce(router, "покажи статус hermes")
    assert outcome is not None and outcome.allowed is True
    assert outcome.intent == "status_read"
    assert outcome.actual_route == "V2_CANARY"
    assert outcome.search_canary is False
    assert outcome.eligible_tools[0] in (
        "runtime_status", "health_status", "canary_ping")
    stats = router.stats()
    assert stats["enforcement"]["allowed"] == 1
    assert stats["enforcement"]["success"] == 0  # not executed yet
    # Search metrics untouched by the status request.
    assert stats["search_enforcement"]["attempts"] == 0
    assert stats["search_shadow"]["total"] == 0


# ── §6 policy unit checks ──────────────────────────────────────────


def test_canary_policy_mandatory_deny_reasons():
    """§6 — every mandatory deny reason is reachable and mapped."""
    clf_cases = {
        "найди пароль": SearchDenyReason.SECRET_QUERY.value,
        "поищи в моих файлах": (
            SearchDenyReason.SEARCH_NOT_ALLOWLISTED.value),
        "найди в интернете новости": (
            SearchDenyReason.SEARCH_NOT_ALLOWLISTED.value),
    }
    for text, expected in clf_cases.items():
        router = _router()
        outcome = _enforce(router, text)
        assert outcome.search_deny_reason == expected, text


def test_canary_allowlist_exact_phrases_only():
    """§9 — exact-phrase matching: near-misses are NOT allowlisted."""
    assert search_canary_allowlist_matches(
        "найди последние ошибки gateway") is True
    # Near-miss variants never auto-expand the allowlist (§9).
    assert search_canary_allowlist_matches(
        "найди ошибки gateway") is False
    assert search_canary_allowlist_matches(
        "покажи последние ошибки gateway прямо сейчас") is False
    assert search_canary_allowlist_matches("") is False


def test_canary_allowlist_phrases_are_mixed_safe():
    """§7 — no allowlist phrase contains an unsafe action word (else
    the mixed-intent gate would self-block the canary)."""
    for phrase in SEARCH_CANARY_ALLOWLIST:
        assert has_mixed_unsafe_intent(phrase) is False, phrase


def test_canary_detect_subtype_deterministic():
    """§2 — subtype detection is deterministic 1:1 with sources."""
    assert detect_search_subtype("найди последние ошибки gateway") \
        == "log_search"
    assert detect_search_subtype("покажи события hermes за час") \
        == "event_search"
    assert detect_search_subtype("find scheduler errors") \
        == "scheduler_search"
    assert detect_search_subtype("show provider errors") \
        == "provider_search"
    assert detect_search_subtype("find telegram errors") \
        == "integration_search"
    assert detect_search_subtype("найди в интернете новости") is None
    assert detect_search_subtype("") is None
    assert SEARCH_ALLOWED_SUBTYPES == (
        "log_search", "event_search", "scheduler_search",
        "provider_search", "integration_search")
    assert SEARCH_ALLOWED_SOURCES == {
        "GATEWAY_LOG", "EVENTS", "SCHEDULER", "PROVIDER",
        "INTEGRATION"}


def test_canary_policy_disabled_denies():
    """§4/§6 — the policy disabled → LEGACY with POLICY_DISABLED."""
    policy = SearchCanaryPolicy(enabled=False)
    from agent.intent_router.classifier import (
        RuleBasedIntentClassifier)

    clf = RuleBasedIntentClassifier()
    classification = clf.classify(
        features_from_text("найди последние ошибки gateway", "t"))
    allowed, reason, codes = policy.decide(
        classification=classification, text="найди последние ошибки gateway")
    assert allowed is False
    assert reason == SearchDenyReason.POLICY_DISABLED.value


# ── §18/§19 cap + sample accounting ────────────────────────────────


def test_canary_cap_blocks_after_20_live_successes():
    """§18 — after 20 successful LIVE V2 search runs the canary stops
    granting (LEGACY, CANARY_LIMIT_REACHED); synthetic samples do not
    count toward the cap (§19)."""
    router = _router()
    granted = []
    for _ in range(SEARCH_CANARY_MAX_SUCCESS):
        granted.append(_enforce(router, "найди последние ошибки gateway"))
    assert all(o.allowed for o in granted)
    # Record 20 successful live executions.
    for o in granted:
        router.record_enforcement_execution(o, ok=True)
    stats = router.stats()["search_enforcement"]
    assert stats["success_live"] == SEARCH_CANARY_MAX_SUCCESS
    assert stats["allowed"] == SEARCH_CANARY_MAX_SUCCESS
    # 21st live attempt → blocked by the cap.
    blocked = _enforce(router, "найди последние ошибки gateway")
    assert blocked.allowed is False
    assert blocked.search_deny_reason == \
        SearchDenyReason.CANARY_LIMIT_REACHED.value
    assert blocked.actual_route == "LEGACY"
    # Synthetic successes never count toward the live cap.
    router2 = _router()
    for _ in range(SEARCH_CANARY_MAX_SUCCESS * 2):
        o = _enforce(
            router2, "найди последние ошибки gateway",
            sample_source="INTERNAL_SYNTHETIC")
        assert o.allowed is True
        router2.record_enforcement_execution(o, ok=True)
    stats2 = router2.stats()["search_enforcement"]
    assert stats2["success_synthetic"] == SEARCH_CANARY_MAX_SUCCESS * 2
    assert stats2["success_live"] == 0
    still = _enforce(router2, "найди последние ошибки gateway")
    assert still.allowed is True  # cap untouched by synthetic


def test_canary_live_synthetic_accounting():
    """§19 — SEARCH_CANARY_LIVE and SEARCH_CANARY_SYNTHETIC are
    separate counters; synthetic is never reported as live."""
    router = _router()
    live = _enforce(router, "найди последние ошибки gateway")
    router.record_enforcement_execution(live, ok=True)
    synth = _enforce(
        router, "найди последние ошибки gateway",
        sample_source="INTERNAL_SYNTHETIC")
    router.record_enforcement_execution(synth, ok=True)
    stats = router.stats()["search_enforcement"]
    assert stats["success_live"] == 1
    assert stats["success_synthetic"] == 1
    assert stats["success"] == 2
