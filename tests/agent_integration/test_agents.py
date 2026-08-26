"""MVP agents are CONTROL-PLANE data producers (Phase 6 §15-§20).

None can execute/grant/mutate/network; CodingAgent's PatchProposal is DATA only
(write_requested is descriptive and never causes a write); MonitoringAgent has
no service-mutation surface.
"""

import pytest

from agent.agent_integration.agents import (
    CodingShadowAgent,
    MemoryAgent,
    MemoryProposal,
    MonitoringAgent,
    PatchProposal,
    PlannerAgent,
    ResearchAgent,
    ReviewVerdict,
    ReviewerAgent,
)
from agent.agent_integration.context import (
    AgentContextAssembler,
    AssembledAgentContext,
)
from agent.agent_integration.result import AgentObservation
from agent.agent_integration.supervisor_state import AgentRunState


class _NarrowMemory:
    def retrieve(self, *, access, query_text, top_k):
        from agent.platform_memory.retrieval import ContextItem

        return (
            ContextItem(key="k1", text="tenant-safe fact", scope="tenant", similarity=1.0),
        )


def _ctx(agent_id="monitoring"):
    return AgentContextAssembler(
        _NarrowMemory(), registry_digest="reg-v1"
    ).assemble(
        task_id="task-1", task_step_id="step-1", agent_id=agent_id,
        tenant_id="acme", user_id="u-1", input_text="input",
        agent_definition_version=1, query_text="q",
        supervisor_state=AgentRunState.READY,
    )


def test_observation_has_no_authority_fields():
    obs = ResearchAgent.run(_ctx("research"))
    d = obs.to_dict()
    assert d["authority_semantics"] is False
    # No execute/approved/grant authority keys on the result model.
    assert "approved" not in d and "grant" not in d and "execute" not in d


def test_research_agent_does_not_auto_network():
    obs = ResearchAgent.run(_ctx("research"))
    assert isinstance(obs, AgentObservation)
    assert "network NOT auto-allowed" in obs.summary
    assert obs.requested_capability  # an intent, not a grant


def test_monitoring_agent_is_read_only_recommendation():
    obs = MonitoringAgent.observe(_ctx("monitoring"), health="unhealthy", status="down")
    assert isinstance(obs, AgentObservation)
    assert "health=unhealthy" in obs.facts
    # On failure: recommendation/escalation, never a service mutation.
    assert obs.recommended_next_step  # recommendation, not restart
    for verb in ("restart", "reload", "stop", "start", "signal"):
        assert verb not in obs.summary.lower()
    # No service-mutation surface exists.
    with pytest.raises(NotImplementedError):
        MonitoringAgent._no_service_mutation_surface()


def test_coding_agent_patch_proposal_is_data_only():
    proposal = CodingShadowAgent.propose_patch(_ctx("coding"), target="x.py", summary="fix")
    assert isinstance(proposal, PatchProposal)
    assert proposal.write_requested is True  # descriptive only
    d = proposal.to_dict()
    assert d["authority_semantics"] is False
    # The vertical NEVER translates this into a filesystem write: CodingShadow
    # has no write surface.
    with pytest.raises(NotImplementedError):
        CodingShadowAgent._no_write_surface()


def test_patch_proposal_with_write_true_never_mutates():
    # REQUIRED test (§20): PatchProposal("write=true") -> no mutation. The
    # proposal object is inert data; no filesystem writer is reachable from it.
    proposal = PatchProposal(agent_id="coding", target="x", summary="s", write_requested=True)
    assert proposal.write_requested is True
    # It carries no side-effecting method and no reference to any writer/executor.
    assert not hasattr(proposal, "apply")
    assert not hasattr(proposal, "write")
    assert not hasattr(proposal, "execute")


def test_reviewer_verdict_is_quality_only():
    obs = AgentObservation(
        agent_run_id="r", agent_id="research",
        summary="found it", facts=("evidence_a",),
    )
    verdict = ReviewerAgent.review(_ctx("reviewer"), obs, require_evidence=("evidence_a",))
    assert verdict.verdict == "accepted"
    assert verdict.recommend_replan is False
    d = verdict.to_dict()
    assert d["authority_semantics"] is False
    with pytest.raises(NotImplementedError):
        ReviewerAgent._no_approval_surface()


def test_reviewer_detects_missing_evidence_and_replans():
    obs = AgentObservation(agent_run_id="r", agent_id="research", summary="partial")
    verdict = ReviewerAgent.review(_ctx("reviewer"), obs, require_evidence=("evidence_a", "evidence_b"))
    assert verdict.verdict == "needs_revision"
    assert verdict.recommend_replan is True
    assert "evidence_a" in verdict.missing_evidence


def test_planner_agent_produces_plan_data():
    plan = PlannerAgent.create_plan(_ctx("planner"), proposed_steps=(("s1", "step one"), ("s2", "step two")))
    assert len(tuple(plan.steps)) == 2
    assert all(getattr(st, "tenant_id", "") == "acme" for st in plan.steps)
    # Planner has no execute/grant/approve surface (pure model objects).
    assert not hasattr(plan, "execute")


def test_memory_agent_only_proposes_and_retrieves():
    proposal = MemoryAgent.propose(_ctx("memory"), action="remember", scope="tenant")
    assert isinstance(proposal, MemoryProposal)
    # No raw backend reference anywhere on the proposal.
    assert not hasattr(proposal, "backend")
    ctx = MemoryAgent.retrieve_context(_ctx("memory"))
    assert isinstance(ctx, AgentObservation)
    assert ctx.facts  # memory snippets are context only


def test_assembled_context_excludes_secrets_and_authority():
    ctx = _ctx()
    assert "credentials" not in ctx.to_dict()
    assert "adapter" not in ctx.to_dict()
    assert "executor" not in ctx.to_dict()
    assert "approval_secret" not in ctx.to_dict()
    assert ctx.to_dict()["authority_semantics"] is False