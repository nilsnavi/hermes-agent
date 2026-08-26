"""Supervisor orchestration flow tests."""

import pytest

from agent.agent_orchestration.router import AgentRouter
from agent.agent_runtime.permissions import AgentPermissions
from agent.agent_runtime.registry import AgentDefinition, AgentRegistry
from agent.agent_orchestration.supervisor import AttemptContext, OutcomeDisposition, OutcomeKind
from agent.agent_orchestration.supervisor_flow import (
    OrchestrationDecision,
    OrchestrationFlowError,
    SupervisorOrchestrationFlow,
    to_escalation_event,
)


def _ctx(*, attempt=1, max_retries=1, alternatives=0, outcome=OutcomeKind.FAILED):
    return AttemptContext(
        attempt=attempt, max_retries=max_retries, alternative_count=alternatives,
        has_side_effect_evidence=False, outcome=outcome,
    )


def _router(defs):
    registry = AgentRegistry(allowed_implementation_ids={"impl-x"})
    for definition in defs:
        registry.register(definition)
    return AgentRouter(registry)


def _alt_router():
    definition = AgentDefinition(
        agent_id="alt", version=1, name="alt", role="agent",
        implementation_id="impl-x", capabilities=("file_read",), trust_score=0.7,
        permissions=AgentPermissions(),
    )
    return _router([definition])


def test_human_review_passthrough():
    decision = SupervisorOrchestrationFlow.run(
        _ctx(outcome=OutcomeKind.UNKNOWN), router=_alt_router(),
        required_capability="file_read",
    )
    assert decision.disposition is OutcomeDisposition.HUMAN_REVIEW
    assert decision.human_review_reason


def test_retry_passthrough():
    decision = SupervisorOrchestrationFlow.run(
        _ctx(attempt=1, max_retries=2), router=_alt_router(),
        required_capability="file_read",
    )
    assert decision.disposition is OutcomeDisposition.RETRY_SAFE


def test_alternative_selects_agent():
    decision = SupervisorOrchestrationFlow.run(
        _ctx(attempt=3, max_retries=2, alternatives=1),
        router=_alt_router(), required_capability="file_read",
        alternative_ids={"alt"},
    )
    assert decision.disposition is OutcomeDisposition.ALTERNATIVE
    assert decision.alternative_agent_id == "alt"


def test_alternative_with_no_route_escalates():
    decision = SupervisorOrchestrationFlow.run(
        _ctx(attempt=3, max_retries=2, alternatives=1),
        router=_alt_router(), required_capability="file_write",
        alternative_ids={"alt"},
    )
    assert decision.disposition is OutcomeDisposition.ESCALATE


def test_flow_rejects_bad_ctx():
    with pytest.raises(OrchestrationFlowError):
        SupervisorOrchestrationFlow.run(
            object(), router=_alt_router(), required_capability="file_read",  # type: ignore[arg-type]
        )


def test_to_escalation_event():
    decision = OrchestrationDecision(
        disposition=OutcomeDisposition.HUMAN_REVIEW, human_review_reason="unknown"
    )
    event = to_escalation_event("t1", "s1", "r1", decision)
    assert event.task_id == "t1"
    assert event.reason == "unknown"


def test_flow_has_no_execution_surface():
    assert not hasattr(SupervisorOrchestrationFlow, "execute")
    assert not hasattr(SupervisorOrchestrationFlow, "dispatch")
    assert not hasattr(SupervisorOrchestrationFlow, "authorize")