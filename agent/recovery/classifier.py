"""Recovery classifier (Sprint 1.0.4) — store-backed disposition.

Wraps the pure function ``agent.persistence.recovery.classify`` (Sprint
1.0.3) with persisted data: run status + event-type sequence from the
durable journal, plus ONE approval-aware refinement:

- A run with a PENDING approval request is waiting for a human decision,
  regardless of its persisted status (a run paused at a gate usually stays
  ``RUNNING`` while the plan waits). Such runs classify
  WAIT_FOR_APPROVAL, not REQUIRES_VERIFICATION — they were never crashed
  mid-tool; execution is deliberately paused.

Everything else matches the frozen 1.0.3 classification table exactly.
"""

from typing import List, Optional

from agent.execution.approval import ApprovalStatus
from agent.execution.events import (
    EXECUTION_COMPLETED,
    PLAN_CREATED,
    STEP_APPROVED,
    STEP_REJECTED,
    STEP_STARTED,
    STEP_WAITING_APPROVAL,
    TOOL_COMPLETED,
    TOOL_FAILED,
    TOOL_STARTED,
)
from agent.persistence.recovery import RecoveryDisposition, classify
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun

# Events that describe EXECUTION progress. Orchestration-level markers
# (ORCHESTRATION_STOPPED, RECOVERY_*, BUDGET_*, RUN_*) must NOT influence
# the tool-outcome analysis — the loop stopping is not a tool outcome.
_EXECUTION_EVENT_TYPES = frozenset({
    PLAN_CREATED, STEP_STARTED, STEP_WAITING_APPROVAL, STEP_APPROVED,
    STEP_REJECTED, TOOL_STARTED, TOOL_COMPLETED, TOOL_FAILED,
    EXECUTION_COMPLETED,
})


class RecoveryClassifier:
    """Deterministic status → disposition mapping against a store."""

    def __init__(self, store) -> None:
        self._store = store

    def classify_run(self, run: AgentRun) -> RecoveryDisposition:
        """Disposition for one persisted run (journal order preserved)."""
        return self.classify_run_with_events(run, self._events_for(run.id))

    def classify_run_with_events(
        self, run: AgentRun, events: List[RuntimeEvent]
    ) -> RecoveryDisposition:
        """Disposition using an already-loaded event trail (scan batching)."""
        execution = [
            e.event_type for e in events if e.event_type in _EXECUTION_EVENT_TYPES
        ]
        disposition = classify(run.status, execution)
        if (
            disposition is RecoveryDisposition.REQUIRES_VERIFICATION
            and self._has_pending_approval(run.id)
        ):
            return RecoveryDisposition.WAIT_FOR_APPROVAL
        return disposition

    def _has_pending_approval(self, run_id: str) -> bool:
        return any(
            a.status is ApprovalStatus.PENDING
            for a in self._store.list_approvals(run_id=run_id)
        )

    def _events_for(self, run_id: str) -> List[RuntimeEvent]:
        return self._store.list_events(run_id=run_id)

    @staticmethod
    def disposition_value(disposition: RecoveryDisposition) -> str:
        return disposition.value
