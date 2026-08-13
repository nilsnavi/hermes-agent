"""Bounded execution loop (Sprint 1.0.5) — the hard-stop guarantee.

Drives the ExecutionEngine ONE step at a time with budget checks between
every step. Even if the planner/executor would return CONTINUE forever,
the budget (journal-derived, durable) terminates the loop: max_steps /
max_tool_calls / max_replans / max_failures / runtime timeout.

Safety invariants enforced here:
- no tool is called without a tool-call budget slot;
- no tool is re-run when its outcome is unknown (TOOL_STARTED without
  TOOL_COMPLETED → MANUAL_REVIEW);
- a completed action is reused, never re-executed (DUPLICATE_ACTION_DETECTED);
- non-idempotent tools are never auto-retried; retries are bounded;
- the run only reaches COMPLETED after ALL steps succeeded AND final
  verification passed.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional

from agent.execution.events import STEP_STARTED, TOOL_FAILED
from agent.execution.models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
from agent.execution.registry import ToolRegistry
from agent.execution.tool_runtime import ToolResult
from agent.execution.verifier import ExecutionVerifier
from agent.runtime.events import RuntimeEvent
from agent.runtime.exceptions import InvalidStateTransition as _IST
from agent.runtime.models import AgentRun
from agent.runtime.run_engine import RunEngine
from agent.runtime.states import RunStatus

from .budget import ExecutionBudget
from .decisions import LoopDecision, StopReason
from .events import DUPLICATE_ACTION_DETECTED
from .exceptions import BudgetExceeded
from .idempotency import (
    DuplicateActionDetector,
    DuplicateStatus,
    compute_input_hash,
)
from .policy import (
    ExecutionPolicy,
    RiskDecision,
    RiskPolicy,
    classify_failure,
    may_retry,
)


@dataclass
class LoopOutcome:
    decision: LoopDecision
    stop_reason: StopReason
    plan: Optional[ExecutionPlan] = None


def _first_non_terminal(plan: ExecutionPlan) -> Optional[int]:
    for index, step in enumerate(plan.steps):
        if step.status not in (StepStatus.COMPLETED, StepStatus.SKIPPED):
            return index
    return None


class ExecutionLoop:
    """One bounded execution pass over a plan."""

    def __init__(
        self,
        store,
        run_engine: RunEngine,
        engine,
        registry: ToolRegistry,
        detector: DuplicateActionDetector,
        risk_policy: RiskPolicy,
        verifier: Optional[ExecutionVerifier] = None,
        clock: Optional[Callable] = None,
    ) -> None:
        self._store = store
        self._run_engine = run_engine
        self._engine = engine
        self._registry = registry
        self._detector = detector
        self._risk = risk_policy
        self._verifier = verifier or ExecutionVerifier()
        self._clock = clock

    # ── entry ────────────────────────────────────────────────────────

    def run(
        self,
        run: AgentRun,
        plan: ExecutionPlan,
        budget: ExecutionBudget,
        policy: ExecutionPolicy,
        task_context,
        cancel_flag: Optional[Callable[[], bool]] = None,
    ) -> LoopOutcome:
        while True:
            if cancel_flag is not None and cancel_flag():
                return self._cancel(run, plan)
            try:
                budget.check_time()
            except BudgetExceeded as exc:
                return LoopOutcome(LoopDecision.BUDGET_EXCEEDED,
                                   budget.stop_reason_for(exc), plan)
            try:
                budget.check_step()
            except BudgetExceeded as exc:
                return LoopOutcome(LoopDecision.BUDGET_EXCEEDED,
                                   budget.stop_reason_for(exc), plan)

            index = _first_non_terminal(plan)
            if index is None:
                return self._finalize(run, plan)
            step = plan.steps[index]

            if step.status is StepStatus.WAITING_APPROVAL:
                if policy.stop_on_approval:
                    return LoopOutcome(LoopDecision.WAIT_APPROVAL,
                                       StopReason.APPROVAL_REQUIRED, plan)
                return LoopOutcome(LoopDecision.CONTINUE,
                                   StopReason.APPROVAL_REQUIRED, plan)

            if step.status is StepStatus.RUNNING:
                outcome = self._resolve_running_step(run, plan, step, budget)
                if outcome is not None:
                    return outcome
                continue  # step reset to READY — retry this iteration

            # PENDING / READY → pre-execution gates
            gate = self._preflight(run, plan, step, budget, policy, task_context)
            if gate is not None:
                return gate  # deny / duplicate / manual review

            granted = self._granted_ids(run.id)
            pauses_at_gate = step.requires_approval and (
                plan.id, step.id) not in granted
            if not pauses_at_gate:
                try:
                    budget.check_tool_call()
                except BudgetExceeded as exc:
                    return LoopOutcome(LoopDecision.BUDGET_EXCEEDED,
                                       budget.stop_reason_for(exc), plan)

            plan = self._engine.execute_next_step(plan,
                                                  approved_step_ids=granted)

            if cancel_flag is not None and cancel_flag():
                return self._cancel(run, plan)

            if plan.status is PlanStatus.COMPLETED:
                return self._finalize(run, plan)
            if plan.status is PlanStatus.FAILED:
                outcome = self._handle_failure(run, plan, budget, policy)
                if outcome is not None:
                    return outcome
                continue  # bounded retry — loop again

    # ── internals ────────────────────────────────────────────────────

    def _resolve_running_step(
        self,
        run: AgentRun,
        plan: ExecutionPlan,
        step: ExecutionStep,
        budget: ExecutionBudget,
    ) -> Optional[LoopOutcome]:
        """A step is RUNNING: only safe when the tool NEVER started."""
        status = self._detector.check(run.id, step.id,
                                      input_hash=compute_input_hash(step.arguments))
        if status is DuplicateStatus.STARTED_NO_COMPLETION:
            self._append(DUPLICATE_ACTION_DETECTED, run.id,
                         step=step.id, action="manual_review")
            return LoopOutcome(LoopDecision.MANUAL_REVIEW,
                               StopReason.MANUAL_REVIEW_REQUIRED, plan)
        # Journal proves the tool never started → safe to reset (exactly once).
        step.status = StepStatus.READY
        self._store.save_step(plan.id, step)
        return None

    def _preflight(
        self,
        run: AgentRun,
        plan: ExecutionPlan,
        step: ExecutionStep,
        budget: ExecutionBudget,
        policy: ExecutionPolicy,
        task_context,
    ) -> Optional[LoopOutcome]:
        """Risk / approval-merge / duplicate checks before ANY tool call."""
        metadata = self._registry.metadata(step.tool)
        risk = self._risk.evaluate(step, metadata, task_context)

        if risk is RiskDecision.DENY:
            step.status = StepStatus.FAILED
            step.error = "denied by risk policy"
            self._store.save_step(plan.id, step)
            self._append(TOOL_FAILED, run.id, step=step.id,
                         status="denied", error=step.error)
            try:
                budget.check_failure()
            except BudgetExceeded as exc:
                return LoopOutcome(LoopDecision.BUDGET_EXCEEDED,
                                   budget.stop_reason_for(exc), plan)
            self._fail_run(run, step.error)
            return LoopOutcome(LoopDecision.FAIL, StopReason.EXECUTION_FAILED, plan)

        # Fail-secure approval merge (§46): plan flag OR tool policy OR risk.
        if risk is RiskDecision.REQUIRE_APPROVAL or metadata.requires_approval:
            step.requires_approval = True  # engine commits the step → gates

        input_hash = compute_input_hash(step.arguments)
        dup = self._detector.check(run.id, step.id, input_hash=input_hash)
        if dup is DuplicateStatus.COMPLETED:
            stored = self._detector.reused_result(plan, step.id)
            if stored is None:
                return LoopOutcome(LoopDecision.MANUAL_REVIEW,
                                   StopReason.MANUAL_REVIEW_REQUIRED, plan)
            self._append(DUPLICATE_ACTION_DETECTED, run.id,
                         step=step.id, action="reuse")
            step.status = StepStatus.COMPLETED
            step.result = stored
            self._store.save_step(plan.id, step)
            return None  # reused — continue the loop (no tool call)
        if dup is DuplicateStatus.STARTED_NO_COMPLETION:
            self._append(DUPLICATE_ACTION_DETECTED, run.id,
                         step=step.id, action="manual_review")
            return LoopOutcome(LoopDecision.MANUAL_REVIEW,
                               StopReason.MANUAL_REVIEW_REQUIRED, plan)
        return None

    def _handle_failure(
        self,
        run: AgentRun,
        plan: ExecutionPlan,
        budget: ExecutionBudget,
        policy: ExecutionPolicy,
    ) -> Optional[LoopOutcome]:
        """Plan just failed: account the failure, maybe retry (bounded)."""
        try:
            budget.check_failure()
        except BudgetExceeded as exc:
            return LoopOutcome(LoopDecision.BUDGET_EXCEEDED,
                               budget.stop_reason_for(exc), plan)

        failed = next((s for s in reversed(plan.steps)
                       if s.status is StepStatus.FAILED), None)
        if failed is None:
            self._fail_run(run, "plan failed without a failed step")
            return LoopOutcome(LoopDecision.FAIL, StopReason.EXECUTION_FAILED, plan)

        metadata = self._registry.metadata(failed.tool)
        status = self._last_failure_status(run.id)
        failure_class = classify_failure(status or "failure", metadata)
        attempts = self._step_attempts(run.id, failed.id)
        if may_retry(failure_class, metadata, attempts, policy):
            failed.status = StepStatus.READY
            plan.status = PlanStatus.RUNNING
            self._store.save_step(plan.id, failed)
            self._store.save_plan(plan)
            return None  # bounded retry — loop again
        self._fail_run(run, failed.error or status or "step failed")
        return LoopOutcome(LoopDecision.FAIL, StopReason.EXECUTION_FAILED, plan)

    def _finalize(self, run: AgentRun, plan: ExecutionPlan) -> LoopOutcome:
        """All steps terminal: VERIFYING → verify → COMPLETED (fail closed)."""
        if plan.status is PlanStatus.RUNNING:
            plan = self._engine.execute_next_step(plan)  # finalize bookkeeping
        try:
            self._run_engine.transition(run, RunStatus.VERIFYING)
        except _IST:
            pass  # already VERIFYING (resume path)
        problems = self._verify_plan(plan)
        if problems:
            self._run_engine.fail_run(run, error="verification failed: " + "; ".join(problems))
            return LoopOutcome(LoopDecision.FAIL, StopReason.VERIFICATION_FAILED, plan)
        result = {
            s.id: s.result for s in plan.steps
            if s.status is StepStatus.COMPLETED and s.result is not None
        }
        self._run_engine.complete_run(run, result=result)
        return LoopOutcome(LoopDecision.COMPLETE, StopReason.COMPLETED, plan)

    def _cancel(self, run: AgentRun, plan: ExecutionPlan) -> LoopOutcome:
        plan = self._engine.cancel_plan(plan)
        self._run_engine.cancel_run(run)
        return LoopOutcome(LoopDecision.CANCEL, StopReason.CANCELLED, plan)

    # ── helpers ──────────────────────────────────────────────────────

    def _verify_plan(self, plan: ExecutionPlan) -> List[str]:
        problems: List[str] = []
        for step in plan.steps:
            if step.status is not StepStatus.COMPLETED:
                continue
            if step.result is None:
                problems.append(f"step {step.id}: completed without result")
                continue
            try:
                result = ToolResult(**step.result)
            except TypeError:
                problems.append(f"step {step.id}: malformed stored result")
                continue
            problems.extend(self._verifier.issues(step, result))
        return problems

    def _granted_ids(self, run_id: str) -> List[str]:
        from agent.execution.approval import ApprovalStatus

        return [
            a.step_id
            for a in self._store.list_approvals(run_id=run_id)
            if a.status is ApprovalStatus.APPROVED
        ]

    def _last_failure_status(self, run_id: str) -> Optional[str]:
        for event in reversed(self._store.list_events(run_id=run_id)):
            if event.event_type == TOOL_FAILED:
                return event.payload.get("status")
        return None

    def _step_attempts(self, run_id: str, step_id: str) -> int:
        return sum(
            1 for e in self._store.list_events(run_id=run_id)
            if e.event_type == STEP_STARTED and e.payload.get("step") == step_id
        )

    def _fail_run(self, run: AgentRun, error: str) -> None:
        self._run_engine.fail_run(run, error=error)

    def _append(self, event_type: str, run_id: str, **payload) -> None:
        event = RuntimeEvent(
            event_type=event_type,
            run_id=run_id,
            timestamp=self._clock() if self._clock else _utcnow(),
            payload=payload,
        )
        self._store.append_event(event)


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
