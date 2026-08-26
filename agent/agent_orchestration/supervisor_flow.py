"""Supervisor orchestration flow.

Ties the SupervisorPolicy classifier to the AgentRouter for alternative routing
and to explicit human-review escalation. The flow produces a sequencing decision
(retry / alternative / escalate / human review) — it never runs tools, never
dispatches execution, and never grants authority. Alternative routing selects an
agent ID; dispatch of actual work stays in the execution kernel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet

from .router import AgentRouter, NoRoute
from .supervisor import (
    AttemptContext,
    EscalationEvent,
    InvalidSupervisorDecision,
    OutcomeDisposition,
    SupervisorPolicy,
)


class OrchestrationFlowError(ValueError):
    """Raised when the orchestration flow receives malformed input."""


@dataclass(frozen=True, slots=True)
class OrchestrationDecision:
    disposition: OutcomeDisposition
    alternative_agent_id: str = ""
    human_review_reason: str = ""


class SupervisorOrchestrationFlow:
    """Pure coordination of supervisor disposition and alternative routing."""

    @staticmethod
    def run(
        ctx: AttemptContext,
        *,
        router: AgentRouter,
        required_capability: str,
        alternative_ids: AbstractSet[str] = frozenset(),
        failed_agent_id: str = "",
    ) -> OrchestrationDecision:
        if type(ctx) is not AttemptContext:
            raise OrchestrationFlowError("ctx must be an exact AttemptContext value")
        if type(router) is not AgentRouter:
            raise OrchestrationFlowError("router must be an exact AgentRouter value")

        # ORCH-003 close: the flow INTERNALLY excludes the failed agent from any
        # alternative routing -- callers no longer need to pre-prune. The failed
        # agent can never be re-selected when an ALTERNATIVE is required.
        candidates = frozenset(a for a in alternative_ids if a != failed_agent_id)
        if failed_agent_id and not candidates:
            # The only alternative WAS the failed agent -> no blind re-dispatch.
            return OrchestrationDecision(
                disposition=OutcomeDisposition.ESCALATE,
                human_review_reason="failed agent excluded, no alternative agent remains",
            )

        disposition = SupervisorPolicy.decide(ctx, alternative_ids=candidates)

        if disposition is OutcomeDisposition.HUMAN_REVIEW:
            return OrchestrationDecision(
                disposition=OutcomeDisposition.HUMAN_REVIEW,
                human_review_reason="ambiguous or side-effectful outcome",
            )

        if disposition is OutcomeDisposition.ALTERNATIVE:
            # Select an alternative agent (routing-only; no dispatch here). The
            # failed agent is already excluded by `candidates`.
            try:
                selection = router.route(
                    required_capability=required_capability,
                    availability=candidates,
                )
            except NoRoute:
                # No alternative eligible (failed excluded) -> escalate.
                return OrchestrationDecision(
                    disposition=OutcomeDisposition.ESCALATE,
                    human_review_reason="no alternative agent eligible",
                )
            return OrchestrationDecision(
                disposition=OutcomeDisposition.ALTERNATIVE,
                alternative_agent_id=selection.agent_id,
            )

        # RETRY_SAFE, ESCALATE, NONE pass through unchanged.
        return OrchestrationDecision(disposition=disposition)


def to_escalation_event(
    task_id: str, step_id: str, run_id: str, decision: OrchestrationDecision
) -> EscalationEvent:
    """Build a typed escalation event from a decision (sink, never executes)."""
    if type(decision) is not OrchestrationDecision:
        raise OrchestrationFlowError("decision must be an exact OrchestrationDecision value")
    reason = decision.human_review_reason or decision.disposition.value
    return EscalationEvent(
        task_id=task_id,
        step_id=step_id,
        run_id=run_id,
        reason=reason,
        disposition=decision.disposition,
    )