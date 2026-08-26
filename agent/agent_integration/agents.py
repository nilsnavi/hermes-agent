"""Phase 6 MVP system agents (CONTROL PLANE, data producers only).

Every agent here is a PURE producer: given a bounded ``AssembledAgentContext``
it returns DATA (observations / plans / verdicts / proposals). None of them
executes a tool, dispatches work, grants a capability, mutates services,
changes policy, or contacts a network source. Network integration for Research
is NOT auto-enabled. CodingAgent produces a ``PatchProposal`` as DATA ONLY --
``write``/``execute`` fields carry zero authority and are never turned into a
filesystem write by this layer. MonitoringAgent only reads and recommends; it
has NO restart/reload/stop/start/signal surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.agent_orchestration.models import TaskPlan, TaskStep

from .capabilities import ReadOnlyCapability
from .context import AssembledAgentContext
from .result import AgentObservation, Citation

_MAX_TEXT_LENGTH = 65_536


def _req(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > _MAX_TEXT_LENGTH:
        raise ValueError(f"{name} exceeds the {_MAX_TEXT_LENGTH}-character limit")
    return value


def _obs(context: AssembledAgentContext, *, summary: str, facts, cap: ReadOnlyCapability,
         reference: str = "") -> AgentObservation:
    return AgentObservation(
        agent_run_id=context.agent_id,
        agent_id=context.agent_id,
        summary=summary,
        facts=tuple(str(f) for f in facts),
        citations=(Citation(source=reference),) if reference else (),
        requested_capability=cap.value,
    )


# --------------------------------------------------------------------------- #
# CodingAgent (shadow / read-only) + PatchProposal (DATA ONLY)                #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class PatchProposal:
    """A proposed change as DATA. ``write_requested`` is descriptive only and is
    NEVER translated into a filesystem write anywhere in this layer."""

    agent_id: str
    target: str
    summary: str
    diff_summary: str = ""
    write_requested: bool = False

    def __post_init__(self) -> None:
        _req("agent_id", self.agent_id)
        _req("target", self.target)
        _req("summary", self.summary)
        if type(self.write_requested) is not bool:
            raise ValueError("write_requested must be a bool")

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "target": self.target,
            "summary": self.summary,
            "diff_summary": self.diff_summary,
            "write_requested": self.write_requested,
            "authority_semantics": False,
        }


class CodingShadowAgent:
    """Analyzes read-only context and may produce a PatchProposal as DATA."""

    @staticmethod
    def analyze(context: AssembledAgentContext) -> AgentObservation:
        return _obs(
            context,
            summary="repository/authorized-code metadata analysis (read-only)",
            facts=(f"{context.input_text} :: analyzed", "no mutation performed"),
            cap=ReadOnlyCapability.SEARCH_INDEX,
        )

    @staticmethod
    def propose_patch(context: AssembledAgentContext, *, target: str, summary: str) -> PatchProposal:
        # DATA ONLY: write_requested is descriptive, never executed here.
        return PatchProposal(
            agent_id=context.agent_id,
            target=target,
            summary=summary,
            diff_summary="shadow diff proposal (not applied)",
            write_requested=True,
        )

    @staticmethod
    def _no_write_surface() -> None:
        """Marker: this agent has no filesystem-write entry point."""
        raise NotImplementedError("CodingShadowAgent cannot write files")


# --------------------------------------------------------------------------- #
# ResearchAgent (no automatic network)                                        #
# --------------------------------------------------------------------------- #

class ResearchAgent:
    """Structured findings from a LOCAL/mock read-only source only."""

    @staticmethod
    def run(context: AssembledAgentContext) -> AgentObservation:
        return _obs(
            context,
            summary="structured findings from a local read-only source (network NOT auto-allowed)",
            facts=("finding: local source context", "network denied by default until certified"),
            cap=ReadOnlyCapability.READ_TEXT_RESOURCE,
        )


# --------------------------------------------------------------------------- #
# PlannerAgent (plan DATA only; never executes / grants / skips supervisor)   #
# --------------------------------------------------------------------------- #

class PlannerAgent:
    @staticmethod
    def create_plan(
        context: AssembledAgentContext,
        *,
        proposed_steps: tuple[tuple[str, str], ...] = (),
    ) -> TaskPlan:
        steps = tuple(
            TaskStep(id=step_id, task_id=context.task_id, tenant_id=context.tenant_id,
                     user_id=context.user_id)
            for step_id, _ in proposed_steps
        )
        return TaskPlan(
            id="plan-" + context.task_id,
            task_id=context.task_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            steps=steps,
        )


# --------------------------------------------------------------------------- #
# ReviewerAgent (quality signal only; cannot approve execution / override SB) #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class ReviewVerdict:
    """Quality-only verdict. Contains NO execution-approval semantics."""

    agent_id: str
    verdict: str  # e.g. "accepted" | "needs_revision" | "uncertain"
    missing_evidence: tuple[str, ...] = ()
    recommend_replan: bool = False
    uncertainty_note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "verdict": self.verdict,
            "missing_evidence": self.missing_evidence,
            "recommend_replan": self.recommend_replan,
            "uncertainty_note": self.uncertainty_note,
            "authority_semantics": False,  # NEVER an execution approval
        }


class ReviewerAgent:
    @staticmethod
    def review(
        context: AssembledAgentContext,
        observation: AgentObservation,
        *,
        require_evidence: tuple[str, ...] = (),
    ) -> ReviewVerdict:
        missing = tuple(e for e in require_evidence if e not in observation.facts)
        if missing:
            return ReviewVerdict(
                agent_id=context.agent_id,
                verdict="needs_revision",
                missing_evidence=missing,
                recommend_replan=True,
                uncertainty_note="missing required evidence",
            )
        return ReviewVerdict(
            agent_id=context.agent_id, verdict="accepted", recommend_replan=False
        )

    @staticmethod
    def _no_approval_surface() -> None:
        raise NotImplementedError("ReviewerAgent cannot approve execution authority")


# --------------------------------------------------------------------------- #
# MonitoringAgent (read-only observations; NO service mutation surface)       #
# --------------------------------------------------------------------------- #

class MonitoringAgent:
    @staticmethod
    def observe(
        context: AssembledAgentContext,
        *,
        health: str,
        status: str,
        metrics: tuple[str, ...] = (),
        audit_summary: str = "",
    ) -> AgentObservation:
        facts = (f"health={health}", f"status={status}", *metrics)
        if audit_summary:
            facts = (*facts, f"audit={audit_summary}")
        # Even on a detected failure, output is a recommendation (no restart etc.).
        summary = "read-only health/status/metrics observation"
        rec = "escalate for human review" if health in ("unhealthy", "unknown") else ""
        obs = _obs(
            context,
            summary=summary,
            facts=facts,
            cap=ReadOnlyCapability.READ_HEALTH,
        )
        if rec:
            obs = AgentObservation(
                agent_run_id=obs.agent_run_id,
                agent_id=obs.agent_id,
                summary=obs.summary,
                facts=obs.facts,
                citations=obs.citations,
                recommended_next_step=rec,
                requested_capability=obs.requested_capability,
            )
        return obs

    @staticmethod
    def _no_service_mutation_surface() -> None:
        raise NotImplementedError("MonitoringAgent cannot restart/reload/stop/start/signal")


# --------------------------------------------------------------------------- #
# MemoryAgent (proposes only; persistence flows through Phase 3 gateway)      #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class MemoryProposal:
    """A proposed memory write -- DATA. The actual persistent workflow must go
    through the Phase 3 Memory Gateway authorization; this agent never touches
    a raw storage backend."""

    agent_id: str
    action: str  # "remember" | "consolidate"
    scope: str
    summary: str


class MemoryAgent:
    @staticmethod
    def retrieve_context(context: AssembledAgentContext) -> AgentObservation:
        return _obs(
            context,
            summary="memory context delta via gateway (retrieval only)",
            facts=context.memory_snippets,
            cap=ReadOnlyCapability.READ_MEMORY_CONTEXT,
        )

    @staticmethod
    def propose(context: AssembledAgentContext, *, action: str, scope: str) -> MemoryProposal:
        return MemoryProposal(
            agent_id=context.agent_id, action=action, scope=scope,
            summary="proposed memory write (requires Phase 3 gateway authorization)",
        )


__all__ = [
    "CodingShadowAgent",
    "MemoryAgent",
    "MemoryProposal",
    "MonitoringAgent",
    "PatchProposal",
    "PlannerAgent",
    "ResearchAgent",
    "ReviewVerdict",
    "ReviewerAgent",
]