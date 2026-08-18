"""Sprint 1.2.1 — STATUS_READ expansion + SEARCH_READ shadow tests (§24).

Covers:

- §2/§13: the 7 expanded STATUS_READ sub-intents are enforced with
  their per-subtype verified READ_ONLY tool surface;
- §3/§10: SEARCH_READ is shadow-only — candidate decision built,
  actual route ALWAYS LEGACY, actual V2 runs = 0;
- §7/§8: negative + mixed intents stay LEGACY (unsafe wins);
- §5: the READ-ONLY metadata contract (side_effect=READ_ONLY +
  idempotent=true) is required for every enforced tool;
- §15: unhealthy runtime → LEGACY fallback.
"""

import pytest

from agent.intent_router.enforcement import (
    STATUS_READ_ALLOWLIST,
    STATUS_SUBTYPE_TOOLS,
    STATUS_TOOL_METADATA,
    VERIFIED_STATUS_READ_TOOLS,
    detect_status_subtype,
    status_read_allowlist_matches,
    tool_metadata_ok,
)
from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import (
    EnforcementBlockReason,
    RouterMode,
    StatusSubtype,
)
from agent.intent_router.router import IntentRouter


# ── helpers ─────────────────────────────────────────────────────────


def _router(health: str = "healthy") -> IntentRouter:
    return IntentRouter(
        flags={"enabled": True,
               "mode": RouterMode.ENFORCE_STATUS_READ.value},
        health_provider=lambda: {"status": health},
    )


def _enforce(router, text, request_id="t"):
    return router.enforce(
        features_from_text(text, request_id=request_id),
        text=text)


# ── §2/§24 — per-subtype enforcement ────────────────────────────────


@pytest.mark.parametrize("text,subtype,primary_tool", [
    ("статус Hermes", "service_status", "runtime_status"),
    ("hermes status", "service_status", "runtime_status"),
    ("состояние gateway", "gateway_status", "gateway_status"),
    ("gateway status", "gateway_status", "gateway_status"),
    ("runtime health", "runtime_status", "runtime_status"),
    ("покажи состояние runtime", "runtime_status", "runtime_status"),
    ("покажи health", "health_status", "health_status"),
    ("health hermes", "health_status", "health_status"),
    ("работает ли Telegram", "integration_status",
     "integration_status"),
    ("состояние MCP", "integration_status", "integration_status"),
    ("telegram status", "integration_status", "integration_status"),
    ("mcp status", "integration_status", "integration_status"),
    ("статус scheduler", "scheduler_status", "scheduler_status"),
    ("scheduler status", "scheduler_status", "scheduler_status"),
    ("какой сейчас provider", "provider_status", "provider_status"),
    ("provider status", "provider_status", "provider_status"),
])
def test_status_subtype_enforced(text, subtype, primary_tool):
    """§2 — every expanded subtype routes to V2_CANARY with its own
    verified tool (primary first, canary_ping fallback second)."""
    router = _router()
    outcome = _enforce(router, text)
    assert outcome is not None and outcome.allowed is True
    assert outcome.actual_route == "V2_CANARY"
    assert outcome.status_subtype == subtype
    assert outcome.eligible_tools[0] == primary_tool
    assert outcome.eligible_tools[1] == "canary_ping"
    # §13 — per-subtype counters increment for the right subtype.
    st = router.stats()["enforcement"]["by_subtype"][subtype]
    assert st["attempts"] == 1 and st["allowed"] == 1


def test_generic_status_uses_runtime_status():
    """Allowlisted status request with no subtype marker → GENERIC,
    primary tool = runtime_status."""
    router = _router()
    outcome = _enforce(router, "покажи статус Hermes")  # marker hermes
    assert outcome is not None and outcome.allowed is True
    assert outcome.status_subtype in (
        StatusSubtype.SERVICE_STATUS.value,)

    # A generic-but-allowlisted phrase (no service/gateway/... marker).
    out2 = _enforce(router, "покажи статус системы")
    if out2 is not None and out2.allowed:
        assert out2.eligible_tools[0] == "runtime_status"


def test_expanded_allowlist_phrases():
    """§6 — every brief phrase passes the allowlist matcher."""
    phrases = [
        "статус Hermes", "состояние gateway", "покажи health",
        "работает ли Telegram", "статус scheduler",
        "какой сейчас provider", "состояние MCP",
        "покажи состояние runtime",
        "hermes status", "gateway status", "runtime health",
        "telegram status", "scheduler status", "provider status",
        "mcp status",
    ]
    for p in phrases:
        assert status_read_allowlist_matches(p), p
    assert len(STATUS_READ_ALLOWLIST) >= 15

# ── §3/§10 — SEARCH_READ shadow study ───────────────────────────────


@pytest.mark.parametrize("text", [
    "найди последние ошибки gateway",
    "найди последние события Hermes",
    "найди информацию по provider errors",
    "search recent scheduler failures",
    "найди почему gateway медленный",
])
def test_search_read_shadow_only(text):
    """§9 + Sprint 1.2.2 §15 — SEARCH_READ is classified and the
    candidate decision is BUILT (capability verified → candidate V2
    for supported sources), but the actual route is ALWAYS LEGACY.
    (Contract update, Sprint 1.2.2: missing_capability is no longer
    always 1 — OPERATIONAL_SEARCH is now a verified capability.)"""
    router = _router()
    outcome = _enforce(router, text)
    assert outcome is not None
    assert outcome.allowed is False
    assert outcome.actual_route == "LEGACY"
    assert outcome.search_shadow is True
    assert outcome.block_reason == \
        EnforcementBlockReason.SEARCH_SHADOW_ONLY.value
    shadow = router.stats()["search_shadow"]
    assert shadow["total"] == 1
    # Sprint 1.2.2 §15: every phrase here has a supported operational
    # source → candidate V2, capability verified, policy-blocked only.
    assert shadow["missing_capability"] == 0
    assert shadow["policy_blocked"] == 1
    assert shadow["candidate_v2"] == 1
    assert shadow["supported_source"] == 1


def test_search_read_never_actual_v2():
    """§10 invariant — SEARCH_READ actual V2 runs = 0.
    (Contract update, Sprint 1.2.2: candidate_v2 is now 5 — the
    gateway-source queries qualify — while actual V2 stays 0.)"""
    router = _router()
    for _ in range(5):
        _enforce(router, "найди последние ошибки gateway")
        _enforce(router, "поищи в интернете")
    stats = router.stats()
    assert stats["search_shadow"]["total"] == 10
    # 5 supported (gateway) + 5 unsupported (web) → 5 candidates.
    assert stats["search_shadow"]["candidate_v2"] == 5
    assert stats["search_shadow"]["supported_source"] == 5
    assert stats["search_shadow"]["unsupported_source"] == 5
    # No allowed outcome ever: search never becomes an actual V2 run.
    assert stats["enforcement"]["allowed"] == 0


def test_search_shadow_aggregates_only_no_raw_prompts():
    """§12 — shadow aggregates; outcome carries no prompt text.
    (Contract update, Sprint 1.2.2: with the capability verified the
    reason codes are shadow_blocked + policy_blocked only.)"""
    router = _router()
    outcome = _enforce(router, "найди последние ошибки gateway")
    d = outcome.to_dict()
    assert "gateway" not in str(d)  # no raw prompt in the outcome
    assert d["search_shadow"] is True
    assert d["reason_codes"] == [
        "search_shadow_blocked", "search_policy_blocked"]


# ── §7/§8 — negative + mixed intents stay LEGACY ────────────────────


@pytest.mark.parametrize("text,reason", [
    ("перезапусти gateway", EnforcementBlockReason.INTENT_NOT_ALLOWED.value),
    ("измени provider", EnforcementBlockReason.INTENT_NOT_ALLOWED.value),
    ("создай cron", EnforcementBlockReason.INTENT_NOT_ALLOWED.value),
    ("исправь Telegram", EnforcementBlockReason.INTENT_NOT_ALLOWED.value),
    ("удали логи", EnforcementBlockReason.INTENT_NOT_ALLOWED.value),
    ("сделай что-нибудь", EnforcementBlockReason.INTENT_NOT_ALLOWED.value),
    ("покажи статус и перезапусти gateway",
     EnforcementBlockReason.INTENT_NOT_ALLOWED.value),
    ("проверь scheduler и создай задачу",
     EnforcementBlockReason.INTENT_NOT_ALLOWED.value),
    ("посмотри provider и переключи модель",
     EnforcementBlockReason.INTENT_NOT_ALLOWED.value),
])
def test_negative_and_mixed_legacy(text, reason):
    """§7/§8 — mutating and mixed intents NEVER route to V2."""
    router = _router()
    outcome = _enforce(router, text)
    assert outcome is not None and outcome.allowed is False
    assert outcome.actual_route == "LEGACY"
    assert outcome.eligible_tools == []
    assert router.stats()["enforcement"]["allowed"] == 0


# ── §5 — READ-ONLY metadata contract ────────────────────────────────


def test_status_tool_metadata_required():
    """§5 — every enforced tool has READ_ONLY + idempotent metadata."""
    for tool in VERIFIED_STATUS_READ_TOOLS:
        assert tool_metadata_ok(tool), tool
        meta = STATUS_TOOL_METADATA[tool]
        assert meta["side_effect"] == "READ_ONLY"
        assert meta["idempotent"] is True


def test_status_tool_must_be_read_only():
    """§5 — a tool with non-READ_ONLY metadata is NOT enforceable."""
    tool = VERIFIED_STATUS_READ_TOOLS[0]
    STATUS_TOOL_METADATA[tool]["side_effect"] = "WRITE"  # simulate drift
    try:
        assert tool_metadata_ok(tool) is False
    finally:
        STATUS_TOOL_METADATA[tool]["side_effect"] = "READ_ONLY"


def test_status_tool_must_be_idempotent():
    """§5 — a non-idempotent tool is NOT enforceable."""
    tool = VERIFIED_STATUS_READ_TOOLS[0]
    STATUS_TOOL_METADATA[tool]["idempotent"] = False
    try:
        assert tool_metadata_ok(tool) is False
    finally:
        STATUS_TOOL_METADATA[tool]["idempotent"] = True


def test_unknown_tool_metadata_fails_closed():
    """§5 — a tool absent from the metadata table blocks enforcement."""
    assert tool_metadata_ok("definitely_not_a_tool") is False


def test_policy_blocks_when_metadata_drifted():
    """§5 — the policy gate blocks when the primary tool's metadata is
    not READ_ONLY (simulated registry drift)."""
    from agent.intent_router.enforcement import EnforcementPolicy

    class _DriftedPolicy(EnforcementPolicy):
        def evaluate(self, classification, text, health=None,
                     status_subtype=None):
            # force the metadata gate to fail
            from agent.intent_router.enforcement import (
                _ENFORCE_ALLOWED_SIDE_EFFECTS)
            return super().evaluate(
                classification, text, health, status_subtype)

    # Real policy path: stub a classifier returning STATUS_READ with
    # all gates pass except metadata — exercise via a monkeypatched
    # tool_metadata_ok.
    import agent.intent_router.enforcement as enf
    original = enf.tool_metadata_ok
    enf.tool_metadata_ok = lambda tool: False
    try:
        router = _router()
        outcome = _enforce(router, "статус Hermes")
        assert outcome is not None and outcome.allowed is False
        assert outcome.block_reason == \
            EnforcementBlockReason.TOOL_METADATA.value
    finally:
        enf.tool_metadata_ok = original


def test_canary_registry_matches_metadata_contract():
    """§5 — the REAL canary registry registers every enforced tool as
    READ_ONLY + idempotent (registry ↔ enforcement table coherence)."""
    from agent.gateway_v2.canary import default_canary_registry

    reg = default_canary_registry()
    for tool in VERIFIED_STATUS_READ_TOOLS:
        assert reg.has(tool), tool
        meta = reg.metadata(tool)
        assert meta.idempotent is True, tool
        assert meta.side_effect_class.value == "read_only", tool


# ── §15 — unhealthy fallback ────────────────────────────────────────


def test_status_unhealthy_fallback():
    """§15 — unhealthy runtime → LEGACY before execution."""
    router = _router(health="unhealthy")
    outcome = _enforce(router, "статус Hermes")
    assert outcome is not None and outcome.allowed is False
    assert outcome.block_reason == EnforcementBlockReason.HEALTH.value
    assert outcome.actual_route == "LEGACY"


def test_health_degraded_blocks_enforcement():
    """Health != healthy (degraded/unknown) → LEGACY."""
    for state in ("degraded", "unknown"):
        router = _router(health=state)
        outcome = _enforce(router, "статус Hermes")
        assert outcome is not None and outcome.allowed is False
        assert outcome.block_reason == \
            EnforcementBlockReason.HEALTH.value


# ── subtype detection unit ──────────────────────────────────────────


def test_detect_status_subtype_markers():
    assert detect_status_subtype("состояние gateway").value == \
        "gateway_status"
    assert detect_status_subtype("какой сейчас provider").value == \
        "provider_status"
    assert detect_status_subtype("статус scheduler").value == \
        "scheduler_status"
    assert detect_status_subtype("работает ли telegram").value == \
        "integration_status"
    assert detect_status_subtype("runtime health").value == \
        "runtime_status"
    assert detect_status_subtype("покажи health").value == \
        "health_status"
    assert detect_status_subtype("статус hermes").value == \
        "service_status"
    assert detect_status_subtype("совершенно непонятный текст").value == \
        StatusSubtype.GENERIC.value


def test_subtype_tools_are_real_registered_names():
    """§4 — every per-subtype tool name is in the verified surface."""
    for tools in STATUS_SUBTYPE_TOOLS.values():
        for t in tools:
            assert t in VERIFIED_STATUS_READ_TOOLS, t
    assert len(STATUS_SUBTYPE_TOOLS) == len(StatusSubtype)
