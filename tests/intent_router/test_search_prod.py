"""Sprint 1.2.4 §34 — SEARCH_READ LIMITED PRODUCTION ENFORCEMENT tests.

Covers the SearchProductionPolicy (HERMES_SEARCH_READ_MODE=
limited_enforce; ALLOW_V2_SEARCH route V2 | LEGACY + mandatory deny
reasons §16), the §4 mode parse (off/shadow/canary/limited_enforce,
unknown → off, canary-flag fallback), the §12 production allowlist
(its OWN 12 phrases — 3 RU phrases differ from the canary list),
§6 mixed-intent safety, §8 secret queries, §11 the 50-live sample
cap (synthetic never counts), §13 empty-result success + §15
search_prod_* metrics by subtype/source, §17 STATUS_READ regression
(unchanged with production mode ON), and §23 negative live cases.

The production mode is ON in every router test here (``search_mode``
= limited_enforce in flags); the canary-flag fallback (search_canary
without search_mode) keeps the 1.2.3 behavior and is covered by
test_search_canary.py.
"""

import pytest

from agent.intent_router.capabilities import CapabilityRegistry
from agent.intent_router.classifier import RuleBasedIntentClassifier
from agent.intent_router.enforcement import (
    SEARCH_ALLOWED_SOURCES,
    SEARCH_ALLOWED_SUBTYPES,
    SEARCH_CANARY_ALLOWLIST,
    SEARCH_PROD_ALLOWLIST,
    SEARCH_PROD_MAX_SUCCESS,
    SearchProductionPolicy,
    detect_search_subtype,
    search_prod_allowlist_matches,
)
from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import (
    RouterMode,
    SearchDenyReason,
)
from agent.intent_router.router import (
    IntentRouter,
    _resolve_search_mode,
    parse_search_mode,
    read_router_flags,
)

# §12 — the production phrases that differ from the canary list (the
# canary list must NOT grant them and vice versa).
PROD_ONLY_PHRASES = (
    "покажи последние события Hermes",
    "покажи последние ошибки provider",
    "покажи ошибки MCP",
)
CANARY_ONLY_PHRASES = (
    "покажи события hermes за последний час",
    "покажи последние provider errors",
    "последние ошибки mcp",
)


def _router(health: str = "healthy", capabilities=None,
            search_mode: str = "limited_enforce") -> IntentRouter:
    return IntentRouter(
        flags={"enabled": True,
               "mode": RouterMode.ENFORCE_STATUS_READ.value,
               "search_mode": search_mode},
        health_provider=lambda: {"status": health},
        capabilities=capabilities,
    )


def _enforce(router, text, request_id="t", sample_source="LIVE"):
    return router.enforce(
        features_from_text(text, request_id=request_id),
        sample_source=sample_source,
        text=text)


# ── §4 mode parse ──────────────────────────────────────────────────


def test_parse_search_mode_values():
    """§4 — only off/shadow/canary/limited_enforce are valid; None and
    any unknown value fail closed to off."""
    assert parse_search_mode("limited_enforce") == "limited_enforce"
    assert parse_search_mode("canary") == "canary"
    assert parse_search_mode("shadow") == "shadow"
    assert parse_search_mode("off") == "off"
    assert parse_search_mode(None) == "off"
    assert parse_search_mode("") == "off"
    assert parse_search_mode("LIMITED_ENFORCE") == "limited_enforce"
    assert parse_search_mode("prod") == "off"       # unknown → off
    assert parse_search_mode("whatever") == "off"   # unknown → off


def test_resolve_search_mode_precedence():
    """§4 — explicit search_mode wins; the legacy canary flag maps to
    canary/shadow; the bare default is shadow."""
    assert _resolve_search_mode({"search_mode": "limited_enforce"}) \
        == "limited_enforce"
    assert _resolve_search_mode({"search_mode": "off"}) == "off"
    # Legacy canary flag (Sprint 1.2.3 flags dicts) still works.
    assert _resolve_search_mode({"search_canary": True}) == "canary"
    assert _resolve_search_mode({"search_canary": False}) == "shadow"
    # Bare default = shadow (the exact 1.2.2 study behavior).
    assert _resolve_search_mode({}) == "shadow"
    assert _resolve_search_mode({"enabled": True}) == "shadow"
    # Unknown explicit value → off (fail closed).
    assert _resolve_search_mode({"search_mode": "bogus"}) == "off"


def test_read_router_flags_mode_env():
    """§4 — HERMES_SEARCH_READ_MODE supersedes the canary flag; absent
    mode falls back to the flag (canary → canary, none → shadow);
    unknown mode value fails closed to off."""
    env = {"HERMES_SEARCH_READ_MODE": "limited_enforce"}
    assert read_router_flags(env)["search_mode"] == "limited_enforce"
    env2 = {"HERMES_SEARCH_READ_MODE": "bogus",
            "HERMES_SEARCH_READ_CANARY": "true"}
    assert read_router_flags(env2)["search_mode"] == "off"
    env3 = {"HERMES_SEARCH_READ_CANARY": "true"}
    assert read_router_flags(env3)["search_mode"] == "canary"
    assert read_router_flags({})["search_mode"] == "shadow"


def test_off_mode_policy_disabled():
    """§4 — HERMES_SEARCH_READ_MODE=off: SEARCH_READ routes LEGACY with
    POLICY_DISABLED and NO shadow metrics are collected (off is
    stricter than shadow)."""
    router = _router(search_mode="off")
    outcome = _enforce(router, "найди последние ошибки gateway")
    assert outcome is not None and outcome.allowed is False
    assert outcome.actual_route == "LEGACY"
    assert outcome.block_reason == SearchDenyReason.POLICY_DISABLED.value
    assert "search_policy_disabled" in outcome.reason_codes
    assert outcome.eligible_tools == []
    assert outcome.search_prod is False
    assert outcome.search_mode == "off"
    stats = router.stats()
    # No shadow study, no prod accounting for the off mode.
    assert stats["search_shadow"]["total"] == 0
    assert stats["search_prod"]["attempts"] == 0


# ── §34 positives: P1-P6 granted through production ────────────────


@pytest.mark.parametrize("text,subtype,source", [
    ("найди последние ошибки gateway", "log_search", "GATEWAY_LOG"),
    ("покажи последние события Hermes", "event_search", "EVENTS"),
    ("найди ошибки scheduler", "scheduler_search", "SCHEDULER"),
    ("покажи последние ошибки provider", "provider_search", "PROVIDER"),
    ("найди ошибки Telegram", "integration_search", "INTEGRATION"),
    ("покажи ошибки MCP", "integration_search", "INTEGRATION"),
    ("find recent gateway errors", "log_search", "GATEWAY_LOG"),
    ("show recent Hermes events", "event_search", "EVENTS"),
    ("find scheduler errors", "scheduler_search", "SCHEDULER"),
    ("show provider errors", "provider_search", "PROVIDER"),
    ("find Telegram errors", "integration_search", "INTEGRATION"),
    ("show MCP errors", "integration_search", "INTEGRATION"),
])
def test_search_prod_allowed(text, subtype, source):
    """§34/§1 — every §12 allowlisted phrase is GRANTED the production
    V2 route (actual_route V2, §9) with the single verified tool."""
    router = _router()
    outcome = _enforce(router, text)
    assert outcome is not None
    assert outcome.allowed is True
    assert outcome.actual_route == "V2"
    assert outcome.search_prod is True
    assert outcome.search_canary is False
    assert outcome.search_mode == "limited_enforce"
    assert outcome.search_subtype == subtype
    assert outcome.search_source == source
    assert outcome.search_deny_reason is None
    assert outcome.eligible_tools == ["operational_log_search"]
    assert len(outcome.eligible_tools) == 1  # §10 — exactly one tool
    assert "search_prod_allowed" in outcome.reason_codes
    assert outcome.policy_version == "search-prod-v1"


def test_search_prod_allowlist_is_own_list():
    """§12 — the production allowlist is the brief's OWN 12 phrases:
    the 3 prod-only RU phrases grant V2, the 3 canary-only phrases do
    NOT (SEARCH_NOT_ALLOWLISTED)."""
    router = _router()
    for text in PROD_ONLY_PHRASES:
        outcome = _enforce(router, text)
        assert outcome.allowed is True, text
        assert outcome.search_deny_reason is None
    for text in CANARY_ONLY_PHRASES:
        outcome = _enforce(router, text)
        assert outcome.allowed is False, text
        assert outcome.actual_route == "LEGACY"
        assert outcome.search_deny_reason == \
            SearchDenyReason.SEARCH_NOT_ALLOWLISTED.value
    # The lists are distinct tuples (12 each) with a known overlap.
    assert len(SEARCH_PROD_ALLOWLIST) == 12
    assert len(SEARCH_CANARY_ALLOWLIST) == 12
    overlap = set(SEARCH_PROD_ALLOWLIST) & set(SEARCH_CANARY_ALLOWLIST)
    assert len(overlap) == 9  # 3 RU phrases differ per brief §12


# ── §34 negatives: never V2 ────────────────────────────────────────


def test_search_prod_secret_query_legacy():
    """§34/§8 — a secret-hunting search NEVER reaches the tool."""
    router = _router()
    outcome = _enforce(router, "найди пароль")
    assert outcome is not None and outcome.allowed is False
    assert outcome.actual_route == "LEGACY"
    assert outcome.search_prod is True
    assert outcome.search_deny_reason == \
        SearchDenyReason.SECRET_QUERY.value
    assert outcome.eligible_tools == []  # tool execution = 0
    assert "search_secret_query" in outcome.reason_codes


def test_search_prod_filesystem_web_legacy():
    """§34/§3/§8 — filesystem and web searches are not allowlisted →
    LEGACY (never operational_log_search)."""
    router = _router()
    for text in ("поищи в моих файлах", "search my files",
                 "найди в интернете последние новости",
                 "grep -R token /home"):
        outcome = _enforce(router, text)
        assert outcome is not None and outcome.allowed is False
        assert outcome.actual_route == "LEGACY"
        assert outcome.eligible_tools == []


def test_search_prod_mixed_unsafe_legacy():
    """§34/§6 — the four §23 mixed-intent classes never reach the
    search branch (unsafe intent always wins)."""
    router = _router()
    cases = {
        "найди и удали последние ошибки gateway": "delete_action",
        "найди ошибку и перезапусти gateway": "system_action",
        "найди ошибки scheduler и создай cron": "write_action",
        "найди ошибки и отправь отчёт": "write_action",
        "сделай это": "unknown",
    }
    for text, intent in cases.items():
        outcome = _enforce(router, text)
        assert outcome is not None and outcome.allowed is False
        assert outcome.intent == intent
        assert outcome.actual_route == "LEGACY"
        assert outcome.search_prod is False  # never reached the branch
        assert outcome.eligible_tools == []


# ── §16 block reasons (policy-level ladder) ────────────────────────


def _classify(text):
    return RuleBasedIntentClassifier().classify(
        features_from_text(text, "t"))


def _policy_decision(policy, text, **kwargs):
    return policy.decide(
        classification=_classify(text), text=text, **kwargs)


def test_search_prod_policy_disabled():
    """§16 — policy disabled → POLICY_DISABLED."""
    policy = SearchProductionPolicy(enabled=False)
    allowed, reason, codes = _policy_decision(
        policy, "найди последние ошибки gateway")
    assert allowed is False
    assert reason == SearchDenyReason.POLICY_DISABLED.value


def test_search_prod_intent_not_search():
    """§16 — a non-SEARCH_READ intent is never granted."""
    policy = SearchProductionPolicy()
    allowed, reason, _ = _policy_decision(policy, "удали ошибки")
    assert allowed is False
    assert reason == SearchDenyReason.SEARCH_NOT_ALLOWLISTED.value


def test_search_prod_mixed_unsafe_gate():
    """§16 — a SEARCH_READ classification whose TEXT also carries an
    unsafe action word → UNSAFE_MIXED_INTENT (before the allowlist;
    the intent gate would already catch a delete/system
    classification — this gate defends the boundary)."""
    from agent.intent_router.classifier import Classification
    from agent.intent_router.models import (
        ExpectedSideEffect, IntentRisk, IntentType,
    )

    policy = SearchProductionPolicy()
    search_with_unsafe_text = Classification(
        intent=IntentType.SEARCH_READ,
        confidence=0.9,
        risk=IntentRisk.LOW,
        expected_side_effect=ExpectedSideEffect.READ_ONLY,
        lexical_hits=["search"],
        reason_codes=["search_read"],
    )
    allowed, reason, codes = policy.decide(
        classification=search_with_unsafe_text,
        text="найди последние ошибки gateway и удали их",
        tool_verified=True, query_ok=True)
    assert allowed is False
    assert reason == SearchDenyReason.UNSAFE_MIXED_INTENT.value
    assert "search_mixed_unsafe_intent" in codes


def test_search_prod_source_not_allowed():
    """§16 — a verified request with a non-operational source →
    SOURCE_NOT_ALLOWED (the SOURCE_NOT_ALLOWED gate, distinct from
    the allowlist miss)."""
    policy = SearchProductionPolicy()
    allowed, reason, _ = _policy_decision(
        policy, "найди последние ошибки gateway",
        subtype="log_search", source="FILESYSTEM",
        tool_verified=True, query_ok=True)
    assert allowed is False
    assert reason == SearchDenyReason.SOURCE_NOT_ALLOWED.value


def test_search_prod_capability_missing():
    """§16 — missing OPERATIONAL_SEARCH capability → CAPABILITY_MISSING."""
    policy = SearchProductionPolicy()
    allowed, reason, _ = _policy_decision(
        policy, "найди последние ошибки gateway",
        source="GATEWAY_LOG", subtype="log_search",
        missing_capabilities=["OPERATIONAL_SEARCH"])
    assert allowed is False
    assert reason == SearchDenyReason.CAPABILITY_MISSING.value


def test_search_prod_tool_not_verified():
    """§16 — unverified tool surface → TOOL_NOT_VERIFIED."""
    policy = SearchProductionPolicy()
    allowed, reason, _ = _policy_decision(
        policy, "найди последние ошибки gateway",
        source="GATEWAY_LOG", subtype="log_search",
        tool_verified=False, query_ok=True)
    assert allowed is False
    assert reason == SearchDenyReason.TOOL_NOT_VERIFIED.value


def test_search_prod_invalid_query():
    """§16 — invalid query → QUERY_INVALID."""
    policy = SearchProductionPolicy()
    allowed, reason, _ = _policy_decision(
        policy, "найди последние ошибки gateway",
        source="GATEWAY_LOG", subtype="log_search",
        tool_verified=True, query_ok=False)
    assert allowed is False
    assert reason == SearchDenyReason.QUERY_INVALID.value


def test_search_prod_health_unavailable():
    """§16 — runtime not healthy → HEALTH_UNAVAILABLE (router-level)."""
    router = _router(health="unknown")
    outcome = _enforce(router, "найди последние ошибки gateway")
    assert outcome is not None and outcome.allowed is False
    assert outcome.search_deny_reason == \
        SearchDenyReason.HEALTH_UNAVAILABLE.value


def test_search_prod_low_confidence():
    """§16 — confidence below the policy threshold → LOW_CONFIDENCE
    (the router computes confidence_ok = conf >= min_confidence; the
    policy gate is exercised with confidence_ok=False)."""
    policy = SearchProductionPolicy(min_confidence=0.95)
    allowed, reason, _ = _policy_decision(
        policy, "найди последние ошибки gateway",
        source="GATEWAY_LOG", subtype="log_search",
        tool_verified=True, query_ok=True, confidence_ok=False)
    assert allowed is False
    assert reason == SearchDenyReason.LOW_CONFIDENCE.value


def test_search_prod_ambiguous():
    """§16 — ambiguous classification → AMBIGUOUS."""
    from agent.intent_router.classifier import Classification
    from agent.intent_router.models import (
        ExpectedSideEffect, IntentRisk, IntentType,
    )

    policy = SearchProductionPolicy()
    ambiguous = Classification(
        intent=IntentType.SEARCH_READ,
        confidence=0.9,
        risk=IntentRisk.LOW,
        expected_side_effect=ExpectedSideEffect.READ_ONLY,
        lexical_hits=["ambiguous"],
        reason_codes=["ambiguous"],
    )
    allowed, reason, _ = policy.decide(
        classification=ambiguous,
        text="найди последние ошибки gateway",
        source="GATEWAY_LOG", subtype="log_search",
        tool_verified=True, query_ok=True)
    assert allowed is False
    assert reason == SearchDenyReason.AMBIGUOUS.value


# ── §11 cap + §15 metrics ──────────────────────────────────────────


def test_search_prod_cap_blocks_after_50_live_successes():
    """§11 — after 50 successful LIVE V2 search runs the production
    mode stops granting (LEGACY, SEARCH_LIMIT_REACHED); synthetic
    samples never count toward the cap."""
    router = _router()
    granted = []
    for _ in range(SEARCH_PROD_MAX_SUCCESS):
        granted.append(_enforce(router, "найди последние ошибки gateway"))
    assert all(o.allowed for o in granted)
    for o in granted:
        router.record_enforcement_execution(o, ok=True)
    stats = router.stats()["search_prod"]
    assert stats["success_live"] == SEARCH_PROD_MAX_SUCCESS
    assert stats["allowed"] == SEARCH_PROD_MAX_SUCCESS
    assert stats["attempts"] == SEARCH_PROD_MAX_SUCCESS
    # 51st live attempt → blocked by the cap.
    blocked = _enforce(router, "найди последние ошибки gateway")
    assert blocked.allowed is False
    assert blocked.actual_route == "LEGACY"
    assert blocked.search_deny_reason == \
        SearchDenyReason.SEARCH_LIMIT_REACHED.value
    assert "search_prod_limit_reached" in blocked.reason_codes
    # Synthetic successes never count toward the live cap.
    router2 = _router()
    for _ in range(SEARCH_PROD_MAX_SUCCESS * 2):
        o = _enforce(
            router2, "найди последние ошибки gateway",
            sample_source="INTERNAL_SYNTHETIC")
        assert o.allowed is True
        router2.record_enforcement_execution(o, ok=True)
    stats2 = router2.stats()["search_prod"]
    assert stats2["success_synthetic"] == SEARCH_PROD_MAX_SUCCESS * 2
    assert stats2["success_live"] == 0
    still = _enforce(router2, "найди последние ошибки gateway")
    assert still.allowed is True  # cap untouched by synthetic


def test_search_prod_metrics_by_subtype_and_source():
    """§15 — attempts/allowed/blocked/success/failure/fallback/empty
    tracked by subtype AND source; deny reasons recorded."""
    router = _router()
    ok = _enforce(router, "найди последние ошибки gateway")
    assert ok.allowed is True
    router.record_enforcement_execution(ok, ok=True)
    empty = _enforce(router, "покажи последние события Hermes")
    assert empty.allowed is True
    router.record_enforcement_execution(empty, ok=True, empty=True)
    blocked = _enforce(router, "найди пароль")
    assert blocked.allowed is False
    stats = router.stats()["search_prod"]
    assert stats["attempts"] == 3
    assert stats["allowed"] == 2
    assert stats["blocked"] == 1
    assert stats["success"] == 2
    assert stats["empty"] == 1
    assert stats["success_live"] == 2
    assert stats["deny_reasons"][SearchDenyReason.SECRET_QUERY.value] == 1
    by_sub = stats["by_subtype"]
    assert by_sub["log_search"]["allowed"] == 1
    assert by_sub["event_search"]["allowed"] == 1
    assert by_sub["event_search"]["empty"] == 1
    by_src = stats["by_source"]
    assert by_src["GATEWAY_LOG"]["allowed"] == 1
    assert by_src["EVENTS"]["allowed"] == 1
    assert by_src["EVENTS"]["empty"] == 1
    # Every granted run counts success via record_enforcement_execution;
    # denied runs never reach success counters.
    assert stats["failure"] == 0
    assert stats["fallback"] == 0


def test_search_prod_failure_and_fallback_accounting():
    """§15 — a granted run that fails or falls back is counted in the
    right bucket; both also tracked by subtype/source."""
    router = _router()
    o1 = _enforce(router, "найди последние ошибки gateway")
    router.record_enforcement_execution(o1, ok=False, fell_back=True)
    o2 = _enforce(router, "покажи последние ошибки provider")
    router.record_enforcement_execution(o2, ok=False)
    stats = router.stats()["search_prod"]
    assert stats["fallback"] == 1
    assert stats["failure"] == 1
    assert stats["success"] == 0
    assert stats["by_subtype"]["log_search"]["fallback"] == 1
    assert stats["by_subtype"]["provider_search"]["failure"] == 1
    assert stats["by_source"]["PROVIDER"]["failure"] == 1


def test_search_prod_empty_is_success_not_fallback():
    """§13 — 0 matches is a VALID success: ok=True + empty=True, never
    a legacy fallback (empty never increments fallback)."""
    router = _router()
    o = _enforce(router, "покажи последние события Hermes")
    assert o.allowed is True
    router.record_enforcement_execution(o, ok=True, empty=True)
    stats = router.stats()["search_prod"]
    assert stats["success"] == 1
    assert stats["empty"] == 1
    assert stats["fallback"] == 0
    # The engine itself returns ok=True with 0 results for a literal
    # that matches nothing (the gateway reports empty, never falls
    # back).
    from agent.operational_search import (
        OperationalSearchEngine,
        SearchRequest,
        SearchSource,
    )

    res = OperationalSearchEngine().search(SearchRequest(
        query="zzz-no-such-literal-12345",
        source=SearchSource.GATEWAY_LOG,
    ))
    assert res.ok is True
    assert len(res.results) == 0


# ── §17 STATUS_READ regression ─────────────────────────────────────


def test_status_read_unchanged_in_production_mode():
    """§17 — with HERMES_SEARCH_READ_MODE=limited_enforce the
    STATUS_READ enforcement path is byte-for-byte unchanged: the same
    allowlisted status requests route V2_CANARY with search_prod
    False and status counters unaffected."""
    router = _router()
    outcome = router.enforce(
        features_from_text("статус gateway", request_id="s1"),
        sample_source="LIVE",
        text="статус gateway")
    assert outcome is not None
    assert outcome.allowed is True
    assert outcome.actual_route == "V2_CANARY"  # status stays canary
    assert outcome.status_subtype == "gateway_status"
    assert outcome.search_prod is False
    assert outcome.search_canary is False
    assert outcome.search_shadow is False
    stats = router.stats()
    assert stats["enforcement"]["allowed"] == 1
    assert stats["enforcement"]["success"] == 0  # not executed yet
    assert stats["search_prod"]["attempts"] == 0
    assert stats["search_shadow"]["total"] == 0


# ── exactly one response / one tool ────────────────────────────────


def test_search_prod_exactly_one_response_one_tool():
    """§9/§10 — one granted production run = exactly ONE outcome with
    a single eligible tool; no shadow+prod double decision."""
    router = _router()
    outcome = _enforce(router, "найди последние ошибки gateway")
    assert outcome.allowed is True
    assert outcome.eligible_tools == ["operational_log_search"]
    assert len(outcome.eligible_tools) == 1
    assert outcome.search_shadow is False
    assert outcome.search_prod is True
    # Deterministic + idempotent: same request → same single decision.
    outcome2 = _enforce(router, "найди последние ошибки gateway")
    assert outcome2.allowed is True
    stats = router.stats()["search_prod"]
    assert stats["attempts"] == 2
    assert stats["allowed"] == 2
    # No canary counters were touched.
    assert router.stats()["search_enforcement"]["attempts"] == 0
