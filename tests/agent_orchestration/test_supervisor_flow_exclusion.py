"""Phase 7 §8 close: SupervisorOrchestrationFlow INTERNALLY excludes the failed
agent from ALTERNATIVE routing (ORCH-003 no longer needs caller pre-pruning)."""

from agent.agent_runtime.registry import AgentDefinition, AgentRegistry
from agent.agent_runtime.permissions import AgentPermissions
from agent.agent_orchestration.router import AgentRouter
from agent.agent_orchestration.supervisor import (
    AttemptContext,
    OutcomeDisposition,
    OutcomeKind,
)
from agent.agent_orchestration.supervisor_flow import SupervisorOrchestrationFlow


def _ctx_alternative():
    return AttemptContext(
        attempt=3, max_retries=2, alternative_count=2,
        has_side_effect_evidence=False, outcome=OutcomeKind.FAILED,
    )


def _def(agent_id: str, impl: str) -> AgentDefinition:
    return AgentDefinition(
        agent_id=agent_id, version=1, name=agent_id, role=agent_id,
        implementation_id=impl, capabilities=("read",), trust_score=0.8,
        permissions=AgentPermissions(read_files=True),
    )


def _router():
    registry = AgentRegistry(allowed_implementation_ids=frozenset({"research-agent", "coding-agent"}))
    registry.register(_def("research", "research-agent"))
    registry.register(_def("coding", "coding-agent"))
    return AgentRouter(registry)


def test_failed_agent_excluded_even_if_caller_passes_it():
    d = SupervisorOrchestrationFlow.run(
        _ctx_alternative(), router=_router(), required_capability="read",
        alternative_ids={"research", "coding"}, failed_agent_id="research",
    )
    assert d.disposition is OutcomeDisposition.ALTERNATIVE
    assert d.alternative_agent_id == "coding"
    assert d.alternative_agent_id != "research"  # failed agent NEVER re-selected


def test_failed_only_alternative_escalates_not_reuse():
    d = SupervisorOrchestrationFlow.run(
        _ctx_alternative(), router=_router(), required_capability="read",
        alternative_ids={"research"}, failed_agent_id="research",
    )
    # The only candidate WAS the failed agent -> no blind re-dispatch.
    assert d.disposition is OutcomeDisposition.ESCALATE
    assert d.alternative_agent_id == ""


def test_no_failed_agent_keeps_prior_behaviour():
    d = SupervisorOrchestrationFlow.run(
        _ctx_alternative(), router=_router(), required_capability="read",
        alternative_ids={"research", "coding"}, failed_agent_id="",
    )
    assert d.disposition is OutcomeDisposition.ALTERNATIVE
    assert d.alternative_agent_id in ("research", "coding")