"""Unknown intent handling (Sprint 1.1 §21, §30, §47)."""

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import RoutingRecommendation


def test_unknown_never_canary(router_healthy):
    d = router_healthy.observe(features_from_text("сделай это", "r"))
    assert d.intent == "unknown"
    assert d.candidate_route != "v2_canary"
    assert d.effective_route != "v2_canary"


def test_unknown_legacy_route(router_healthy):
    for text in ("сделай это", "проверь", "запусти", "исправь"):
        d = router_healthy.observe(features_from_text(text, "r"))
        assert d.effective_route == "legacy", text


def test_unknown_recommendation_enum(router_healthy):
    d = router_healthy.observe(features_from_text("проверь", "r"))
    assert d.recommended_route == RoutingRecommendation.LEGACY.value


def test_unknown_confidence_low(router_healthy):
    d = router_healthy.observe(features_from_text("сделай это", "r"))
    assert d.confidence is not None
    assert d.confidence < 0.5


def test_unknown_reason_code(router_healthy):
    d = router_healthy.observe(features_from_text("сделай это", "r"))
    assert "unknown_intent" in d.reason_codes
