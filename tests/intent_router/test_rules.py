"""Routing rules tests (Sprint 1.1 §19, §30, §62-64)."""

from agent.intent_router.models import RoutingRecommendation
from agent.intent_router.rules import RULES, list_rules


def test_rules_ordered_and_auditable():
    ids = [r["id"] for r in RULES]
    assert ids == [f"R{i}" for i in range(1, len(RULES) + 1)]
    for rule in RULES:
        assert rule["description"]
        assert rule["candidate"].value in (
            "legacy", "v2_shadow", "v2_canary",
            "require_approval", "deny", "unknown",
        )


def test_default_rule_is_legacy():
    # Last rule (R8) = default → LEGACY (fail closed).
    assert RULES[-1]["candidate"] is RoutingRecommendation.LEGACY


def test_write_delete_rules_never_canary():
    for rule in RULES:
        if rule["id"] in ("R1", "R2", "R3", "R4"):
            assert rule["candidate"] is not RoutingRecommendation.V2_CANARY


def test_unknown_rule_legacy():
    r5 = next(r for r in RULES if r["id"] == "R5")
    assert r5["candidate"] is RoutingRecommendation.LEGACY


def test_schedule_rule_legacy():
    r3 = next(r for r in RULES if r["id"] == "R3")
    assert r3["candidate"] is RoutingRecommendation.LEGACY


def test_system_rule_not_canary():
    r1 = next(r for r in RULES if r["id"] == "R1")
    assert r1["candidate"] is not RoutingRecommendation.V2_CANARY


def test_list_rules_safe_view():
    view = list_rules()
    assert len(view) == len(RULES)
    for item in view:
        assert "description" in item
        assert "intents" in item
        assert "candidate" in item
