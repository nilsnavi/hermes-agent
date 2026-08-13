"""Risk integration tests (Sprint 1.1 §9, §26, §29)."""

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import IntentRisk
from agent.intent_router.router import IntentRouter


def test_status_low_risk():
    from agent.intent_router.classifier import RuleBasedIntentClassifier

    c = RuleBasedIntentClassifier().classify(
        features_from_text("покажи статус сервера", "r"))
    assert c.risk is IntentRisk.LOW


def test_delete_critical_risk():
    from agent.intent_router.classifier import RuleBasedIntentClassifier

    c = RuleBasedIntentClassifier().classify(
        features_from_text("удали файл", "r"))
    assert c.risk is IntentRisk.CRITICAL


def test_system_high_risk():
    from agent.intent_router.classifier import RuleBasedIntentClassifier

    c = RuleBasedIntentClassifier().classify(
        features_from_text("перезапусти gateway", "r"))
    assert c.risk is IntentRisk.HIGH


def test_critical_risk_never_canary(router_healthy):
    d = router_healthy.observe(features_from_text(
        "удали файл", "r", internal=True))
    assert d.effective_route != "v2_canary"
    assert d.candidate_route != "v2_canary"


def test_risk_policy_authoritative():
    # The execution risk policy (ConservativeRiskPolicy) stays the
    # authority; the router's risk class is a preliminary label only.
    from agent.execution.registry import SideEffectClass, ToolMetadata
    from agent.orchestrator.policy import (
        ConservativeRiskPolicy, RiskDecision,
    )
    from agent.runtime.context import TaskContext

    policy = ConservativeRiskPolicy()
    step = type("S", (), {
        "tool": "runtime_status",
        "requires_approval": False,
    })()
    metadata = ToolMetadata(
        idempotent=True, side_effect_class=SideEffectClass.READ_ONLY,
    )
    ctx = TaskContext(goal="g", risk_level="critical",
                      allowed_tools=["runtime_status"])
    decision = policy.evaluate(step, metadata, ctx)
    assert decision is RiskDecision.REQUIRE_APPROVAL


def test_approval_routing_does_not_permit(router_healthy):
    # REQUIRE_APPROVAL recommendation ≠ execution will be allowed.
    d = router_healthy.observe(features_from_text(
        "отправь сообщение", "r", internal=True))
    assert d.recommended_route in ("require_approval", "legacy")
    assert d.effective_route == "legacy"
