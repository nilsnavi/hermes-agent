"""Verification recovery (Sprint 1.0.4) — persisted-state verification.

For REQUIRES_VERIFICATION runs this checks whether the durable journal and
persisted step results PROVE that every started tool completed. It never
calls a tool, never guesses, never re-runs anything — it only reads.

A step is considered unconfirmed when:
- TOOL_STARTED exists without a later TOOL_COMPLETED for that step
  (the process died mid-tool → outcome unknown), or
- a step row claims COMPLETED but has no persisted result (data
  inconsistency — committed atomically, so this flags corruption).
"""

from datetime import datetime
from typing import Callable, Dict, List, Optional

from agent.execution.events import TOOL_COMPLETED, TOOL_STARTED
from agent.execution.models import StepStatus
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun

from .models import VerificationResult


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class VerificationRecovery:
    """Read-only verification against the persisted store."""

    def __init__(self, store, clock: Optional[Callable[[], datetime]] = None) -> None:
        self._store = store
        self._clock = clock or _utcnow

    def verify(self, run: AgentRun) -> VerificationResult:
        events: List[RuntimeEvent] = self._store.list_events(run_id=run.id)
        started: Dict[str, int] = {}
        completed: Dict[str, int] = {}
        for event in events:
            step = event.payload.get("step")
            if not step:
                continue
            if event.event_type == TOOL_STARTED:
                started[step] = started.get(step, 0) + 1
            elif event.event_type == TOOL_COMPLETED:
                completed[step] = completed.get(step, 0) + 1

        missing: List[str] = []
        reasons: List[str] = []
        for step_id, count in sorted(started.items()):
            if completed.get(step_id, 0) < count:
                missing.append(step_id)
                reasons.append(
                    f"TOOL_STARTED without TOOL_COMPLETED for step {step_id}"
                )

        # Cross-check persisted plan rows (result must exist for COMPLETED).
        for plan in self._store.list_plans(run_id=run.id):
            for step in plan.steps:
                if step.status is StepStatus.COMPLETED and step.result is None:
                    missing.append(step.id)
                    reasons.append(
                        f"step {step.id} marked COMPLETED without persisted result"
                    )

        return VerificationResult(
            run_id=run.id,
            ok=not missing,
            missing_steps=missing,
            reasons=reasons,
        )
