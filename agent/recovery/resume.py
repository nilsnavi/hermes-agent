"""Resume coordinator (Sprint 1.0.4) — controlled safe resume of ONE run.

Rules enforced here (safety contract):

- ONLY ``SAFE_TO_RESUME`` runs are resumed; every other disposition raises
  :class:`NotResumable`.
- ``REQUIRES_VERIFICATION`` runs are first verified against PERSISTED state
  (journal + step results). If the journal cannot prove every started tool
  completed → manual review, never auto-resume.
- A step in ``RUNNING`` is only ever reset-and-resumed when the journal
  proves the tool NEVER started (no TOOL_STARTED for that step). If
  TOOL_STARTED exists without TOOL_COMPLETED → the outcome is unknown →
  manual review. No tool is ever re-run with unknown outcome.
- An existing ``WAITING_APPROVAL`` gate is preserved — no second approval
  request is created; the run keeps waiting on the ORIGINAL decision.
- Completed/skipped steps are never re-executed.
- All decisions are written to the durable journal (recovery audit trail).
"""

from datetime import datetime
from typing import Callable, List, Optional

from agent.execution.approval import ApprovalStatus
from agent.execution.events import STEP_APPROVED
from agent.execution.executor import ExecutionEngine
from agent.execution.models import ExecutionPlan, PlanStatus, StepStatus
from agent.persistence.recovery import RecoveryDisposition
from agent.runtime.models import AgentRun
from agent.runtime.run_engine import RunEngine
from agent.runtime.states import RunStatus

from .classifier import RecoveryClassifier
from .events import (
    RECOVERY_MANUAL_REVIEW,
    RECOVERY_RESUMED,
    RECOVERY_VERIFIED,
    RECOVERY_WAITING,
)
from .exceptions import NotResumable, RecoveryErrorBase
from .models import RunRecoveryResult
from .verification import VerificationRecovery


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


_TERMINAL_PLANS = (PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED)


class ResumeCoordinator:
    """Drive one run from a persisted state through a fresh engine."""

    def __init__(
        self,
        store,
        run_engine: Optional[RunEngine] = None,
        verifier: Optional[VerificationRecovery] = None,
        classifier: Optional[RecoveryClassifier] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._store = store
        self._run_engine = run_engine
        self._verifier = verifier or VerificationRecovery(store, clock=clock)
        self._classifier = classifier or RecoveryClassifier(store)
        self._clock = clock or _utcnow

    # ── public ───────────────────────────────────────────────────────

    def approve(
        self,
        run_id: str,
        approval_id: str,
        engine: Optional[ExecutionEngine] = None,
    ) -> RunRecoveryResult:
        """Decide a PERSISTED approval (post-restart path) and resume.

        The engine's in-session ApprovalManager does not survive a restart,
        so this decides against the durable approval row: atomic
        (approval decision + step state + STEP_APPROVED event in ONE
        transaction), version-guarded, and duplicate decisions are refused.
        The granted gate is seeded into the fresh engine so the step does
        NOT re-trigger a second approval request.
        """
        approval = self._store.get_approval(approval_id)
        if approval.status is not ApprovalStatus.PENDING:
            raise RecoveryErrorBase(
                f"approval {approval_id} already decided: {approval.status.value}"
            )
        run = self._store.get_run(run_id)
        if run.status.is_terminal:
            # §35 (Sprint 1.0.5): a late approval must never revive a
            # cancelled (or otherwise terminal) run — fail closed.
            raise RecoveryErrorBase(
                f"run {run_id} is {run.status.value} — approval refused"
            )
        plans = self._active_plans(run_id)
        if not plans:
            raise RecoveryErrorBase(f"run {run_id} has no active plan")
        plan = plans[0]
        step = plan.step(approval.step_id)
        if step is None or step.status is not StepStatus.WAITING_APPROVAL:
            raise RecoveryErrorBase(
                f"step {approval.step_id} is not waiting for approval"
            )

        approval.status = ApprovalStatus.APPROVED
        step.status = StepStatus.READY  # gate passed → runnable on resume
        with self._store.transaction():
            self._store.update_approval(approval)
            self._store.save_step(plan.id, step)
            self._append(STEP_APPROVED, run_id,
                         step=approval.step_id, approval=approval.id)
        if run.status is RunStatus.WAITING_APPROVAL:
            if self._run_engine is None:
                raise NotResumable(
                    "run must transition waiting_approval -> approved; RunEngine required"
                )
            self._run_engine.transition(run, RunStatus.APPROVED)
        return self.resume(run_id, engine=engine)

    def resume(
        self,
        run_id: str,
        engine: Optional[ExecutionEngine] = None,
    ) -> RunRecoveryResult:
        """Controlled resume of one run.

        *engine* must be an ExecutionEngine bound to the SAME store
        (``engine.store is store``); without it the coordinator only
        classifies and reports (action ``resume_ready``) — nothing runs.
        """
        run = self._store.get_run(run_id)
        events = self._store.list_events(run_id=run_id)
        disposition = self._classifier.classify_run_with_events(run, events)

        if disposition is RecoveryDisposition.MANUAL_REVIEW:
            self._queue_manual(run_id, run.status.value, "ambiguous tool outcome in journal")
            return self._result(run, disposition, "manual_review",
                                "TOOL_STARTED without TOOL_COMPLETED — no automatic retry")

        if disposition is RecoveryDisposition.WAIT_FOR_APPROVAL:
            self._append(RECOVERY_WAITING, run_id, reason="approval pending")
            return self._result(run, disposition, "wait",
                                "existing approval pending — no new approval request")

        if disposition is RecoveryDisposition.TERMINAL:
            return self._result(run, disposition, "ignore", "terminal state")

        if disposition is RecoveryDisposition.REQUIRES_VERIFICATION:
            verified = self._verify_or_queue(run)
            if not verified:
                return self._result(run, disposition, "manual_review",
                                    "verification could not confirm tool outcomes")
            self._append(RECOVERY_VERIFIED, run_id, reason="persisted state verified")
            # Fall through: verified REQUIRES_VERIFICATION resumes like SAFE_TO_RESUME.

        # ── SAFE_TO_RESUME (or verified) ─────────────────────────────
        plans = self._active_plans(run_id)
        if not plans:
            self._append(RECOVERY_WAITING, run_id, reason="needs_planning")
            return self._result(run, disposition, "needs_planning",
                                "no persisted plan — planning must be re-driven by caller")

        plan = plans[0]
        start = self._start_index(plan)
        if start is None:
            # All steps already completed — finish the bookkeeping only.
            return self._complete_plan(run, plan, disposition)

        first_status = plan.steps[start].status
        if first_status is StepStatus.WAITING_APPROVAL:
            self._append(RECOVERY_WAITING, run_id,
                         reason=f"plan {plan.id} paused on existing approval")
            return self._result(run, disposition, "wait",
                                f"step {plan.steps[start].id} waits on existing approval")

        if first_status is StepStatus.RUNNING:
            return self._handle_running_step(run, plan, start, engine, disposition)

        # first_status is PENDING / READY → safe to continue.
        if engine is None:
            return self._result(run, disposition, "resume_ready",
                                "classified resumable — engine required to execute")

        if engine.store is not self._store:
            raise RecoveryErrorBase("engine must be bound to the same store instance")

        self._ensure_running(run)
        self._append(RECOVERY_RESUMED, run_id,
                     reason=f"resuming plan {plan.id} from step index {start}")
        try:
            plan = engine.resume_plan(plan, approved_step_ids=self._approved_ids(run_id))
        except RecoveryErrorBase:
            raise
        except Exception as exc:  # execution failure → fail the run, never hide it
            self._fail_run(run, str(exc))
            return self._result(run, disposition, "failed", f"resume error: {exc}")

        if plan.status is PlanStatus.COMPLETED:
            return self._complete_plan(run, plan, disposition)
        if plan.status is PlanStatus.FAILED:
            self._fail_run(run, self._plan_error(plan))
            return self._result(run, disposition, "failed",
                                f"plan failed during resume: {self._plan_error(plan)}")
        # Plan still RUNNING → paused on a (possibly new) approval gate.
        return self._result(run, disposition, "resumed",
                            f"plan {plan.id} running; paused or in progress")

    # ── internals ────────────────────────────────────────────────────

    def _active_plans(self, run_id: str) -> List[ExecutionPlan]:
        plans = self._store.list_plans(run_id=run_id)
        return [p for p in plans if p.status not in _TERMINAL_PLANS]

    def _approved_ids(self, run_id: str) -> List[str]:
        """Step ids whose approval gates were already granted (persisted)."""
        return [
            a.step_id
            for a in self._store.list_approvals(run_id=run_id)
            if a.status is ApprovalStatus.APPROVED
        ]

    @staticmethod
    def _start_index(plan: ExecutionPlan) -> Optional[int]:
        for i, step in enumerate(plan.steps):
            if step.status not in (StepStatus.COMPLETED, StepStatus.SKIPPED):
                return i
        return None

    def _handle_running_step(
        self,
        run: AgentRun,
        plan: ExecutionPlan,
        start: int,
        engine: Optional[ExecutionEngine],
        disposition: RecoveryDisposition,
    ) -> RunRecoveryResult:
        """A step is RUNNING: only safe to retry when the tool NEVER ran."""
        step = plan.steps[start]
        if self._tool_started_for(run.id, step.id):
            self._queue_manual(run.id, run.status.value,
                               f"step {step.id}: TOOL_STARTED without TOOL_COMPLETED")
            return self._result(run, disposition, "manual_review",
                                f"step {step.id} outcome unknown — no automatic retry")
        # Journal proves the tool never started → reset to READY and continue.
        step.status = StepStatus.READY
        self._store.save_step(plan.id, step)
        reason = f"step {step.id} reset (tool never started)"
        if engine is None:
            return self._result(run, disposition, "resume_ready", reason)
        if engine.store is not self._store:
            raise RecoveryErrorBase("engine must be bound to the same store instance")
        self._ensure_running(run)
        self._append(RECOVERY_RESUMED, run_id=run.id,
                     reason=f"{reason}; resuming plan {plan.id}")
        try:
            plan = engine.resume_plan(plan, approved_step_ids=self._approved_ids(run.id))
        except Exception as exc:
            self._fail_run(run, str(exc))
            return self._result(run, disposition, "failed", f"resume error: {exc}")
        if plan.status is PlanStatus.COMPLETED:
            return self._complete_plan(run, plan, disposition)
        if plan.status is PlanStatus.FAILED:
            self._fail_run(run, self._plan_error(plan))
            return self._result(run, disposition, "failed",
                                f"plan failed during resume: {self._plan_error(plan)}")
        return self._result(run, disposition, "resumed",
                            f"plan {plan.id} running after step reset")

    def _tool_started_for(self, run_id: str, step_id: str) -> bool:
        events = self._store.list_events(run_id=run_id)
        return any(
            e.event_type == "TOOL_STARTED" and e.payload.get("step") == step_id
            for e in events
        )

    def _verify_or_queue(self, run: AgentRun) -> bool:
        result = self._verifier.verify(run)
        if result.ok:
            return True
        self._queue_manual(run.id, run.status.value,
                           "; ".join(result.reasons) or "verification failed")
        return False

    def _queue_manual(self, run_id: str, run_status: str, reason: str) -> None:
        self._append(RECOVERY_MANUAL_REVIEW, run_id, reason=reason,
                     run_status=run_status)

    def _ensure_running(self, run: AgentRun) -> None:
        """Move the run into RUNNING where legally possible."""
        if run.status is RunStatus.RUNNING:
            return
        if run.status in (RunStatus.PLANNING, RunStatus.APPROVED):
            if self._run_engine is None:
                raise NotResumable(
                    f"run {run.id} must transition {run.status.value} -> running; "
                    "RunEngine required"
                )
            self._run_engine.transition(run, RunStatus.RUNNING)
            return
        raise NotResumable(
            f"run {run.id} status {run.status.value} cannot safely reach RUNNING"
        )

    def _complete_plan(
        self,
        run: AgentRun,
        plan: ExecutionPlan,
        disposition: RecoveryDisposition,
    ) -> RunRecoveryResult:
        """Plan finished: finish run bookkeeping (VERIFYING → COMPLETED)."""
        if self._run_engine is None:
            return self._result(run, disposition, "plan_completed",
                                "plan done — run completion requires RunEngine")
        try:
            if run.status is RunStatus.RUNNING:
                self._run_engine.transition(run, RunStatus.VERIFYING)
            result = {
                s.id: s.result for s in plan.steps
                if s.status is StepStatus.COMPLETED and s.result is not None
            }
            self._run_engine.complete_run(run, result=result)
        except Exception as exc:  # pragma: no cover - defensive
            raise RecoveryErrorBase(f"run completion failed: {exc}") from exc
        return self._result(run, disposition, "completed",
                            "resumed plan completed; run completed")

    def _fail_run(self, run: AgentRun, error: str) -> None:
        if self._run_engine is None:
            return
        self._run_engine.fail_run(run, error=error)

    @staticmethod
    def _plan_error(plan: ExecutionPlan) -> str:
        for step in plan.steps:
            if step.status is StepStatus.FAILED and step.error:
                return step.error
        return "plan failed"

    def _append(self, event_type: str, run_id: str, **payload) -> None:
        from agent.runtime.events import RuntimeEvent

        event = RuntimeEvent(
            event_type=event_type,
            run_id=run_id,
            timestamp=self._clock(),
            payload=payload,
        )
        self._store.append_event(event)

    @staticmethod
    def _result(
        run: AgentRun,
        disposition: RecoveryDisposition,
        action: str,
        reason: str,
    ) -> RunRecoveryResult:
        return RunRecoveryResult(
            run_id=run.id,
            run_status=run.status.value,
            disposition=disposition.value,
            action=action,
            reason=reason,
        )
