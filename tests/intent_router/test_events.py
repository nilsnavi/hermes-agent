"""Router event tests (Sprint 1.1 §40, §83)."""

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.events import (
    INTENT_ROUTER_ERROR,
    INTENT_ROUTER_EVALUATED,
    router_error_payload,
    router_event_payload,
)
from agent.intent_router.router import IntentRouter


def test_event_ring_records_decisions(router_healthy):
    router_healthy.observe(features_from_text("покажи статус", "r1"))
    events = router_healthy.recent_events()
    assert events
    assert events[0].event_type == INTENT_ROUTER_EVALUATED


def test_event_contains_no_prompt(router_healthy):
    router_healthy.observe(features_from_text(
        "покажи статус сервера секрет-abc", "r1"))
    raw = str(router_healthy.recent_events()[-1].to_dict())
    assert "секрет" not in raw
    assert "abc" not in raw
    assert "prompt" not in raw


def test_event_whitelisted_fields(router_healthy):
    """§9: payload carries exactly the Sprint 1.1.1 whitelisted fields —
    scalars and counts only, never prompt/args/secrets."""
    router_healthy.observe(features_from_text("покажи статус", "r1"))
    payload = router_healthy.recent_events()[-1].payload
    allowed = {
        "request_id", "intent", "risk", "expected_side_effect",
        "candidate_route", "effective_route", "actual_route",
        "confidence", "confidence_bucket", "reason_codes",
        "required_capability_count", "missing_capability_count",
        "matched", "duration_ms", "router_version", "policy_version",
        "mode", "sample_source",
    }
    assert set(payload.keys()) == allowed
    assert payload["sample_source"] == "LIVE"
    assert payload["actual_route"] is None  # not supplied → not inferred


def test_error_event_recorded():
    from agent.intent_router.classifier import IntentClassifier

    class Boom(IntentClassifier):
        def classify(self, features):
            raise ValueError("nope")

    r = IntentRouter(classifier=Boom(),
                     flags={"enabled": True, "mode": "observe"})
    r.observe(features_from_text("что-то", "r1"))
    assert r.stats()["errors"] == 1
    events = r.recent_events()
    assert any(e.event_type == INTENT_ROUTER_ERROR for e in events)


def test_error_event_no_secrets():
    payload = router_error_payload("r1", "ValueError", "v1", "observe")
    assert payload["request_id"] == "r1"
    assert "error_class" in payload
    assert "prompt" not in payload


def test_event_payload_builder_whitelist():
    payload = router_event_payload(
        request_id="r1", intent="status_read", risk="low",
        candidate_route="v2_canary", effective_route="v2_canary",
        confidence=0.9, reason_codes=["read_only_intent"],
        capabilities=["READ_RUNTIME_STATUS"], duration_ms=0.5,
        router_version="v1", mode="observe",
    )
    assert "request_id" in payload
    assert "text" not in payload
    assert "prompt" not in payload
    assert payload["confidence_bucket"] == "0.9-1.0"
