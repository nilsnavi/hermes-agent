"""Sprint 1.2.2 §20 — SEARCH_READ router tests.

Covers the §15 candidate gate (tool verified, source supported,
query safe, health good, confidence threshold) and §18 negative
cases — with SEARCH_READ actual V2 = 0 invariant held everywhere.
"""

import pytest

from agent.intent_router.capabilities import CapabilityRegistry
from agent.intent_router.enforcement import (
    SEARCH_TOOL_METADATA,
    VERIFIED_SEARCH_TOOLS,
    detect_search_source,
    search_tool_metadata_ok,
)
from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import (
    EnforcementBlockReason,
    RouterMode,
)
from agent.intent_router.router import IntentRouter


def _router(health: str = "healthy", capabilities=None) -> IntentRouter:
    return IntentRouter(
        flags={"enabled": True,
               "mode": RouterMode.ENFORCE_STATUS_READ.value},
        health_provider=lambda: {"status": health},
        capabilities=capabilities,
    )


def _enforce(router, text, request_id="t"):
    return router.enforce(
        features_from_text(text, request_id=request_id),
        text=text)


# ── §20 — 7 mandatory router tests ─────────────────────────────────


def test_search_read_requires_operational_search_capability():
    """§20/§15 — without the OPERATIONAL_SEARCH capability the
    candidate is NEVER V2 (missing capability), route stays LEGACY."""
    caps = CapabilityRegistry(capabilities={
        "READ_RUNTIME_STATUS": "status only surface"})
    router = _router(capabilities=caps)
    outcome = _enforce(router, "найди последние ошибки gateway")
    assert outcome is not None and outcome.allowed is False
    assert outcome.actual_route == "LEGACY"
    assert outcome.search_candidate_v2 is False
    assert outcome.search_missing_capability is True
    assert "search_missing_capability" in outcome.reason_codes


def test_search_read_candidate_v2_when_verified():
    """§20/§15 — verified capability + supported source + safe query
    + healthy + confidence → candidate V2 (but NEVER the route)."""
    router = _router()
    outcome = _enforce(router, "найди последние ошибки gateway")
    assert outcome is not None
    assert outcome.search_shadow is True
    assert outcome.search_candidate_v2 is True
    assert outcome.search_source == "GATEWAY_LOG"
    assert outcome.search_supported_source is True
    assert outcome.search_query_safe is True
    assert outcome.eligible_tools == ["operational_log_search"]
    assert outcome.actual_route == "LEGACY"  # §15 — route stays legacy


def test_search_read_actual_route_still_legacy():
    """§20/§15 — even a full candidate never becomes V2: allowed
    stays False, block reason SEARCH_SHADOW_ONLY, actual LEGACY."""
    router = _router()
    outcome = _enforce(router, "покажи события Hermes за час")
    assert outcome is not None and outcome.allowed is False
    assert outcome.search_candidate_v2 is True
    assert outcome.search_source == "EVENTS"
    assert outcome.block_reason == \
        EnforcementBlockReason.SEARCH_SHADOW_ONLY.value
    assert outcome.actual_route == "LEGACY"
    # No allowed outcome ever for search.
    assert router.stats()["enforcement"]["allowed"] == 0


def test_web_search_stays_legacy():
    """§20/§18 N6 — a web/general search is not an operational search:
    unsupported source → no candidate, LEGACY."""
    router = _router()
    outcome = _enforce(router, "найди в интернете последние новости")
    assert outcome is not None and outcome.allowed is False
    assert outcome.search_shadow is True
    assert outcome.search_candidate_v2 is False
    assert outcome.search_source is None
    assert outcome.search_supported_source is False
    assert "search_unsupported_source" in outcome.reason_codes
    assert outcome.actual_route == "LEGACY"


def test_search_delete_mixed_legacy():
    """§20/§18 N4 — a search+delete mix is DELETE_ACTION → LEGACY
    (unsafe wins; never a search candidate)."""
    router = _router()
    outcome = _enforce(router, "найди и удали ошибки")
    assert outcome is not None and outcome.allowed is False
    assert outcome.intent == "delete_action"
    assert outcome.search_shadow is False
    assert outcome.search_candidate_v2 is False
    assert outcome.actual_route == "LEGACY"


def test_search_system_mixed_legacy():
    """§20/§18 N5 — a search+system mix is SYSTEM_ACTION → LEGACY."""
    router = _router()
    outcome = _enforce(router,
                       "найди ошибку и перезапусти gateway")
    assert outcome is not None and outcome.allowed is False
    assert outcome.intent == "system_action"
    assert outcome.search_candidate_v2 is False
    assert outcome.actual_route == "LEGACY"


def test_secret_search_denied():
    """§20/§18 N1/N2 — a secret-hunting search is never a candidate:
    secret_query blocks it, route LEGACY."""
    router = _router()
    for text in ("найди пароль", "покажи OPENAI_API_KEY"):
        outcome = _enforce(router, text)
        assert outcome is not None and outcome.allowed is False
        assert outcome.actual_route == "LEGACY"
        assert outcome.search_candidate_v2 is False
        if outcome.search_shadow:
            assert outcome.search_secret_query is True
            assert "search_secret_query" in outcome.reason_codes


# ── §16/§3 unit checks ─────────────────────────────────────────────


def test_detect_search_source_q1_q5():
    """§17 — the 5 controlled search cases map deterministically."""
    assert detect_search_source(
        "найди последние ошибки gateway") == "GATEWAY_LOG"
    assert detect_search_source(
        "покажи события Hermes за час") == "EVENTS"
    assert detect_search_source(
        "найди последние scheduler errors") == "SCHEDULER"
    assert detect_search_source(
        "покажи ошибки provider за 15 минут") == "PROVIDER"
    assert detect_search_source(
        "последние ошибки Telegram") == "INTEGRATION"


def test_detect_search_source_web_and_empty():
    assert detect_search_source("найди в интернете новости") is None
    assert detect_search_source("") is None
    assert detect_search_source(None) is None


def test_search_tool_metadata_contract():
    """§3 — the verified search tool carries the READ-ONLY contract."""
    assert "operational_log_search" in VERIFIED_SEARCH_TOOLS
    assert search_tool_metadata_ok("operational_log_search") is True
    meta = SEARCH_TOOL_METADATA["operational_log_search"]
    assert meta["side_effect"] == "READ_ONLY"
    assert meta["idempotent"] is True
    assert meta["network"] is False
    assert set(meta["sources"]) == {
        "GATEWAY_LOG", "EVENTS", "SCHEDULER", "PROVIDER",
        "INTEGRATION"}
    assert "OPERATIONAL_SEARCH" in meta["capabilities"]
    # Unknown tool → fail closed.
    assert search_tool_metadata_ok("cat") is False


def test_search_metrics_accumulate():
    """§22 — supported/unsupported/invalid/secret/low-confidence are
    counted per observation class."""
    router = _router()
    _enforce(router, "найди последние ошибки gateway")  # supported
    _enforce(router, "найди в интернете новости")        # unsupported
    _enforce(router, "найди пароль")                     # secret
    stats = router.stats()["search_shadow"]
    assert stats["total"] == 3
    assert stats["supported_source"] == 1
    assert stats["unsupported_source"] == 2
    assert stats["secret_query"] == 1
    assert stats["candidate_v2"] == 1
    assert stats["policy_blocked"] == 3
    # The §10/§27 invariant: search never becomes an actual V2 run.
    assert router.stats()["enforcement"]["allowed"] == 0


def test_search_shadow_actual_v2_zero_invariant():
    """§10/§27 — SEARCH_READ actual V2 runs = 0 across many requests."""
    router = _router()
    for _ in range(10):
        _enforce(router, "найди последние ошибки gateway")
    stats = router.stats()
    assert stats["search_shadow"]["total"] == 10
    assert stats["search_shadow"]["candidate_v2"] == 10
    assert stats["enforcement"]["allowed"] == 0  # actual V2 = 0
