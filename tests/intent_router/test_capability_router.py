"""Sprint 1.3.0 §15/§16/§35 — Capability Router V2 integration tests.

Covers: feature-flag parse (§15, unknown → off), off-mode inertness,
shadow-mode comparison (§13 — legacy decision stands, evidence
recorded), enforce-mode scope (§16 Phase B/C — the EXACT 1.2.4
surface), the §35 equivalence corpus (S1-S7 STATUS_READ, P1-P12
SEARCH_READ production allowlist, N1-N8 unsafe negatives — enforce
outcome byte-identical to legacy), §29/§30 metrics and §31
performance (10k deterministic resolutions).
"""

import time

from agent.capability_router.router import benchmark_resolutions
from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import RouterMode
from agent.intent_router.router import (
    IntentRouter,
    parse_capability_router_mode,
    read_router_flags,
)

# ── §35 equivalence corpus ──────────────────────────────────────────
# S1-S7: one STATUS_READ phrase per verified subtype.
S_CASES = [
    # NOTE: `route` here is the CAPABILITY router's canonical bucket (V2),
    # NOT the legacy 1.2.4 bucket (V2_CANARY). The capability router
    # canonicalizes V2_CANARY → V2 (§16 Phase B); the legacy decision is
    # asserted separately via `_legacy_signature` (actual_route=V2_CANARY).
    ("покажи статус Hermes", "V2", "runtime_status", None),
    ("статус gateway", "V2", "gateway_status", None),
    ("покажи состояние runtime", "V2", "runtime_status", None),
    ("покажи health", "V2", "health_status", None),
    ("работает ли telegram", "V2", "integration_status", None),
    ("статус scheduler", "V2", "scheduler_status", None),
    ("какой сейчас provider", "V2", "provider_status", None),
]
# P1-P12: the Sprint 1.2.4 §12 production allowlist (12 phrases).
P_CASES = [
    ("найди последние ошибки gateway", "V2", "operational_log_search", None),
    ("покажи последние события hermes", "V2", "operational_log_search", None),
    ("найди ошибки scheduler", "V2", "operational_log_search", None),
    ("покажи последние ошибки provider", "V2", "operational_log_search", None),
    ("найди ошибки telegram", "V2", "operational_log_search", None),
    ("покажи ошибки mcp", "V2", "operational_log_search", None),
    ("find recent gateway errors", "V2", "operational_log_search", None),
    ("show recent hermes events", "V2", "operational_log_search", None),
    ("find scheduler errors", "V2", "operational_log_search", None),
    ("show provider errors", "V2", "operational_log_search", None),
    ("find telegram errors", "V2", "operational_log_search", None),
    ("show mcp errors", "V2", "operational_log_search", None),
]
# N1-N8: unsafe / not-allowlisted negatives.
N_CASES = [
    ("найди пароль в логах", "LEGACY", None, "SECRET_QUERY"),
    ("покажи события hermes за последний час", "LEGACY", None,
     "SEARCH_NOT_ALLOWLISTED"),
    ("последние ошибки mcp", "LEGACY", None, "SEARCH_NOT_ALLOWLISTED"),
    ("удали файл отчёта", "LEGACY", None, "INTENT_NOT_ALLOWED"),
    ("перезапусти gateway", "LEGACY", None, "INTENT_NOT_ALLOWED"),
    ("напомни мне завтра в 9 утра", "LEGACY", None, "INTENT_NOT_ALLOWED"),
    ("отправь сообщение Ивану", "LEGACY", None, "INTENT_NOT_ALLOWED"),
    ("одобри approval run_123", "LEGACY", None, "INTENT_NOT_ALLOWED"),
]
ALL_CASES = [(p, *rest, "status") for p, *rest in S_CASES] + \
    [(p, *rest, "search") for p, *rest in P_CASES] + \
    [(p, *rest, "neg") for p, *rest in N_CASES]


def _router(cap_mode="off", search_mode="limited_enforce",
            health="healthy"):
    return IntentRouter(
        flags={"enabled": True,
               "mode": RouterMode.ENFORCE_STATUS_READ.value,
               "search_mode": search_mode,
               "capability_router_mode": cap_mode},
        health_provider=lambda: {"status": health},
    )


def _enforce(router, text, request_id="t", sample_source="LIVE"):
    return router.enforce(
        features_from_text(text, request_id=request_id),
        sample_source=sample_source,
        text=text)


def _legacy_signature(outcome):
    """The decision-affecting fields (route/tool/reason) of an outcome."""
    return (
        outcome.allowed,
        outcome.actual_route,
        outcome.eligible_tools[0] if outcome.eligible_tools else None,
        outcome.block_reason,
    )


# ── §15 flag parse ──────────────────────────────────────────────────


def test_parse_capability_router_mode_strict():
    assert parse_capability_router_mode("off") == "off"
    assert parse_capability_router_mode("shadow") == "shadow"
    assert parse_capability_router_mode("enforce") == "enforce"
    assert parse_capability_router_mode("ENFORCE") == "enforce"
    assert parse_capability_router_mode(None) == "off"
    assert parse_capability_router_mode("") == "off"
    assert parse_capability_router_mode("bogus") == "off"  # unknown → off
    assert parse_capability_router_mode("true") == "off"


def test_read_router_flags_capability_mode_env():
    env = {"HERMES_CAPABILITY_ROUTER_V2": "enforce"}
    assert read_router_flags(env)["capability_router_mode"] == "enforce"
    env2 = {"HERMES_CAPABILITY_ROUTER_V2": "bogus",
            "HERMES_SEARCH_READ_MODE": "limited_enforce"}
    flags = read_router_flags(env2)
    assert flags["capability_router_mode"] == "off"  # unknown fails closed
    assert flags["search_mode"] == "limited_enforce"  # sibling untouched
    assert read_router_flags({})["capability_router_mode"] == "off"


# ── off mode is inert ───────────────────────────────────────────────


def test_off_mode_inert_zero_overhead():
    """off (the default) → enforcement outcome has NO capability
    evidence and the capability router counts nothing."""
    r = _router("off")
    o = _enforce(r, "покажи статус Hermes")
    assert o.allowed is True
    assert o.capability_route is None
    assert o.capability_router_mode == "off"
    assert r.stats()["capability_router"]["decisions"] == 0


# ── shadow mode: legacy stands, evidence recorded ───────────────────


def test_shadow_mode_legacy_decision_stands():
    """§13 — in shadow the legacy (1.2.4) decision is untouched."""
    legacy = _router("off")
    shadow = _router("shadow")
    for phrase, route, tool, reason, family in ALL_CASES:
        lo = _enforce(legacy, phrase, request_id=f"leg-{phrase[:8]}")
        so = _enforce(shadow, phrase, request_id=f"sh-{phrase[:8]}")
        assert _legacy_signature(so) == _legacy_signature(lo), phrase
        assert so.capability_route == route, phrase
        assert so.capability_router_mode == "shadow"


def test_shadow_mode_equivalence_matches_all_cases():
    """§30 — for the canonical corpus every shadow comparison matches
    on route, tool and reason (acceptance: mismatch = 0)."""
    r = _router("shadow")
    for phrase, route, tool, reason, family in ALL_CASES:
        o = _enforce(r, phrase, request_id=f"eq-{phrase[:8]}")
        assert o.match_route is True, f"route mismatch: {phrase}"
        assert o.match_tool is True, f"tool mismatch: {phrase}"
        assert o.match_reason is True, f"reason mismatch: {phrase}"
    stats = r.stats()["capability_router"]
    assert stats["decisions"] == len(ALL_CASES)
    assert stats["comparison"]["route_mismatch"] == 0
    assert stats["comparison"]["tool_mismatch"] == 0
    assert stats["comparison"]["reason_mismatch"] == 0
    assert stats["denied"] == 0  # §22 DENY never fires in 1.3.0


# ── enforce mode: byte-identical to legacy for the 1.2.4 scope ──────


def test_enforce_equivalent_to_legacy_all_cases():
    """§35 — enforce-mode outcomes are byte-identical to the legacy
    1.2.4 outcomes on route/tool/reason for the whole corpus."""
    legacy = _router("off")
    enforce = _router("enforce")
    for phrase, route, tool, reason, family in ALL_CASES:
        lo = _enforce(legacy, phrase, request_id=f"l-{phrase[:8]}")
        eo = _enforce(enforce, phrase, request_id=f"e-{phrase[:8]}")
        assert _legacy_signature(eo) == _legacy_signature(lo), phrase
        assert eo.capability_route == route, phrase
        assert eo.match_route is True, phrase
        assert eo.match_tool is True, phrase
        assert eo.match_reason is True, phrase


def test_enforce_status_read_v2_tool_per_subtype():
    """§16 Phase B — STATUS_READ routes V2_CANARY with the per-subtype
    verified tool (exactly one tool, §17)."""
    r = _router("enforce")
    for phrase, route, tool, reason in S_CASES:
        o = _enforce(r, phrase, request_id=f"s-{phrase[:8]}")
        assert o.allowed is True, phrase
        assert o.actual_route == "V2_CANARY", phrase
        assert o.eligible_tools == [tool], phrase
        assert o.capability_tool == tool, phrase
    # max_tool_calls=1: exactly one eligible tool (no canary_ping).
    assert all(len(o.eligible_tools) == 1 for o in
               [_enforce(r, p) for p, *_ in S_CASES])


def test_enforce_search_limited_prod_v2():
    """§16 Phase C — SEARCH_READ limited production allowlist routes V2
    via operational_log_search."""
    r = _router("enforce")
    for phrase, route, tool, reason in P_CASES:
        o = _enforce(r, phrase, request_id=f"p-{phrase[:8]}")
        assert o.allowed is True, phrase
        assert o.actual_route == "V2", phrase
        assert o.eligible_tools == ["operational_log_search"], phrase
        assert o.search_prod is True, phrase


def test_enforce_negatives_stay_legacy():
    """N1-N8 — unsafe/not-allowlisted requests stay LEGACY with the
    exact legacy block reason."""
    r = _router("enforce")
    for phrase, route, tool, reason in N_CASES:
        o = _enforce(r, phrase, request_id=f"n-{phrase[:8]}")
        assert o.allowed is False, phrase
        assert o.actual_route == "LEGACY", phrase
        assert o.block_reason == reason, phrase


def test_enforce_no_new_intent_authority():
    """§11/§16 — no production expansion: off-scope read intents
    (INFORMATION_READ etc.) never gain V2 authority."""
    r = _router("enforce")
    for phrase in ("покажи список файлов", "прочитай конфиг",
                   "найди информацию про налоги"):
        o = _enforce(r, phrase, request_id=f"x-{phrase[:8]}")
        assert o.allowed is False, phrase
        assert o.actual_route == "LEGACY", phrase


def test_enforce_search_canary_mode_preserved():
    """The capability router has NO authority outside limited_enforce:
    in canary mode the legacy canary branch keeps granting V2_CANARY."""
    legacy = _router("off", search_mode="canary")
    enforce = _router("enforce", search_mode="canary")
    lo = _enforce(legacy, "найди последние ошибки gateway")
    eo = _enforce(enforce, "найди последние ошибки gateway")
    assert _legacy_signature(eo) == _legacy_signature(lo)
    # canary allowlist phrase still gets V2_CANARY through legacy path
    o = _enforce(enforce, "найди последние ошибки gateway")
    assert o.actual_route == "V2_CANARY"
    assert o.capability_route == "LEGACY"  # cap router: out of scope
    assert o.match_route is False  # documented canary-scope mismatch


def test_enforce_fails_closed_on_error():
    """Any capability-router failure fails closed to the legacy
    outcome (1.2.4 behavior — §48 rollback semantics)."""

    class _Broken:
        mode = "enforce"

        def decide(self, **kw):
            raise RuntimeError("boom")

    r = _router("off")
    r._capability_router = _Broken()  # noqa: SLF001
    r._capability_router_mode = "enforce"
    o = _enforce(r, "покажи статус Hermes")
    # legacy outcome stands (allowed), no crash
    assert o.allowed is True
    assert o.actual_route == "V2_CANARY"


# ── §29/§30 metrics ─────────────────────────────────────────────────


def test_metrics_surface():
    r = _router("enforce")
    for phrase, *_ in ALL_CASES:
        _enforce(r, phrase)
    stats = r.stats()["capability_router"]
    assert stats["decisions"] == len(ALL_CASES)
    assert stats["allowed"] == len(S_CASES) + len(P_CASES)
    assert stats["legacy"] == len(N_CASES)
    assert stats["denied"] == 0
    assert stats["by_intent"]["status_read"] == len(S_CASES)
    # N1-N3 are search-scoped (secret/allowlist denies) → they resolve
    # OPERATIONAL_SEARCH too: 12 allowlist + 3 search negatives = 15.
    assert stats["by_intent"]["search_read"] == len(P_CASES) + 3
    assert stats["by_capability"]["STATUS_GATEWAY"] == 1
    assert stats["by_capability"]["OPERATIONAL_SEARCH"] == len(P_CASES) + 3
    assert stats["by_tool"]["operational_log_search"] == len(P_CASES) + 3
    # N4-N8 (delete/system/schedule/write/approval) resolve to
    # NO_CAPABILITY; N1 secret / N2-N3 allowlist stay search-scoped.
    # Sprint 1.3.1 §2 — reason codes are canonical (UPPER_SNAKE).
    assert stats["by_reason"]["CAPABILITY_UNSUPPORTED"] == 5
    assert stats["by_reason"]["SECRET_QUERY"] == 1
    assert stats["by_reason"]["ALLOWLIST_MISS"] == 2
    assert stats["comparison"]["decision_match"] == len(ALL_CASES)
    # router health carries the capability_router section
    health = r.health()
    assert health["capability_router"]["mode"] == "enforce"
    assert health["capability_router"]["decisions"] == len(ALL_CASES)


# ── §31 performance ─────────────────────────────────────────────────


def test_10k_deterministic_resolutions_performant():
    """§31 — resolver p95 < 1 ms, full router p95 < 5 ms."""
    res = benchmark_resolutions(10000)
    assert res["resolver"]["p95_ms"] < 1.0, res["resolver"]
    assert res["router"]["p95_ms"] < 5.0, res["router"]


def test_router_decide_well_under_5ms_per_decision():
    """Integration-level perf guard: 5,000 full enforce decisions stay
    well under the 5 ms/decision gate."""
    r = _router("shadow")
    t0 = time.perf_counter()
    n = 5000
    for i in range(n):
        _enforce(r, "покажи статус Hermes", request_id=f"perf{i}")
    elapsed = time.perf_counter() - t0
    per = elapsed / n * 1000.0
    assert per < 5.0, f"{per:.3f} ms/decision too slow"
    assert r.stats()["errors"] == 0
