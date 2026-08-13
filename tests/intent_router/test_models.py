"""Model + serialization tests (Sprint 1.1 §12-13, §35)."""

from agent.intent_router.models import (
    IntentRisk,
    IntentRoutingDecision,
    IntentType,
    RequestIntentFeatures,
    RoutingRecommendation,
    confidence_bucket,
)


def test_intent_enum_values():
    assert IntentType.STATUS_READ.value == "status_read"
    assert IntentType.DELETE_ACTION.value == "delete_action"
    assert IntentType.UNKNOWN.value == "unknown"


def test_risk_separate_from_intent():
    # Intent != Risk: a read intent is LOW, delete is CRITICAL.
    assert IntentRisk.LOW.value == "low"
    assert IntentRisk.CRITICAL.value == "critical"


def test_recommendation_enum():
    assert RoutingRecommendation.V2_CANARY.value == "v2_canary"
    assert RoutingRecommendation.LEGACY.value == "legacy"
    assert RoutingRecommendation.REQUIRE_APPROVAL.value == "require_approval"
    assert RoutingRecommendation.DENY.value == "deny"


def test_decision_candidate_vs_effective():
    d = IntentRoutingDecision(
        request_id="r1", intent="status_read", risk="low",
        expected_side_effect="read_only",
        recommended_route="legacy", candidate_route="v2_canary",
        effective_route="legacy", confidence=0.9,
        reason_codes=["canary_disabled"],
    )
    out = d.to_dict()
    assert out["candidate_route"] == "v2_canary"
    assert out["effective_route"] == "legacy"
    assert out["confidence_bucket"] == "0.9-1.0"


def test_decision_no_raw_payload():
    d = IntentRoutingDecision(
        request_id="r1", intent="unknown", risk="unknown",
        expected_side_effect="unknown",
        recommended_route="legacy", candidate_route="legacy",
        effective_route="legacy", confidence=0.4,
        reason_codes=["unknown_intent"],
    )
    out = d.to_dict()
    # No prompt, no args, no secret fields.
    for forbidden in ("prompt", "text", "args", "token", "secret"):
        assert forbidden not in out


def test_confidence_buckets():
    assert confidence_bucket(0.4) == "0.0-0.5"
    assert confidence_bucket(0.6) == "0.5-0.7"
    assert confidence_bucket(0.8) == "0.7-0.9"
    assert confidence_bucket(0.95) == "0.9-1.0"
    assert confidence_bucket(1.0) == "0.9-1.0"
    assert confidence_bucket(None) is None


def test_features_never_hold_prompt():
    f = RequestIntentFeatures(request_id="r1", lexical_hits=["status"])
    assert "text" not in f.to_dict()
    assert f.lexical_hits == ["status"]


def test_decision_json_stable_schema():
    import json

    d = IntentRoutingDecision(
        request_id="r1", intent="status_read", risk="low",
        expected_side_effect="read_only",
        recommended_route="legacy", candidate_route="v2_canary",
        effective_route="legacy", confidence=0.9,
        reason_codes=["canary_disabled"],
        required_capabilities=["READ_RUNTIME_STATUS"],
        eligible_tools=["runtime_status", "canary_ping"],
        classifier_version="rule-v1", policy_version="policy-v1",
        timestamp="2026-08-12T00:00:00+00:00",
    )
    s1 = json.dumps(d.to_dict(), sort_keys=True)
    s2 = json.dumps(d.to_dict(), sort_keys=True)
    assert s1 == s2  # stable
