"""Allowlist gate tests (Sprint 1.1 §27, §35)."""

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.router import IntentRouter


def _router(canary=True):
    return IntentRouter(
        flags={"enabled": True, "mode": "observe",
               "canary": canary, "shadow": True},
        health_provider=lambda: {"status": "healthy"},
    )


def test_internal_allowlisted_canary():
    r = _router()
    d = r.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert d.canary_eligible is True
    assert d.effective_route == "v2_canary"


def test_non_allowlisted_read_legacy():
    r = _router()
    d = r.observe(features_from_text("покажи статус сервера", "r1"))
    assert d.canary_eligible is False
    assert d.effective_route == "legacy"
    assert "canary_allowlist_required" in d.reason_codes


def test_canary_flag_off_effective_legacy():
    r = _router(canary=False)
    d = r.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    # candidate canary requires flag; with flag off → legacy.
    assert d.effective_route == "legacy"
    assert d.canary_eligible is False


def test_shadow_eligible_read():
    """§28/§66: shadow is broader — it covers ALLOWLISTED read intents
    without a verified V2 capability (canary cannot serve those; shadow
    can). A non-allowlisted read stays legacy (MUST-HAVE #3)."""
    r = _router()
    # search_read has NO verified capability → canary not a candidate,
    # shadow is. Allowlisted + healthy → effective v2_shadow.
    d = r.observe(features_from_text(
        "найди информацию про налоги", "r1", internal=True))
    assert d.shadow_eligible is True
    assert d.candidate_route == "v2_shadow"
    assert d.effective_route == "v2_shadow"
    # and non-allowlisted reads never get effective V2 (MUST-HAVE #3)
    d2 = r.observe(features_from_text("покажи статус сервера", "r1"))
    assert d2.effective_route == "legacy"
