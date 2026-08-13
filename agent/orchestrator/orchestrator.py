"""Runtime orchestrator (Sprint 1.0.5) — bounded lifecycle driver.

Wires RunEngine → Planner → PlanValidator → RiskPolicy → ExecutionEngine →
ToolRuntime → Verifier → Persistent Store → RecoveryEngine into ONE
bounded execution loop. Orchestration ONLY: no planner logic, no tool
execution, no state machine, no recovery classification is duplicated
here — each concern stays in its owning module.

Public API:
- run(task_context, policy=None, step_specs=None)  — new bounded run
- resume(run_id, policy=None, step_specs=None)     — safe continuation
- approve(run_id, approval_id, policy=None)        — decide a persisted approval
- cancel(run_id)                                   — cooperative cancellation
- inspect(run_id)                                  — read-only
- request_replan(run_id, ...)                      — budget-gated replan
- dry_run(task_context, ...)                       — ZERO writes, ZERO tools

NOT connected to the production gateway (activation is a later sprint).
"""

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from agent.execution.approval import ApprovalStatus  # noqa: F401  (reserved)
from agent.execution.events import utcnow
from agent.execution.executor import ExecutionEngine
from agent.execution.exceptions import InvalidPlan
from agent.execution.models import ExecutionPlan, PlanStatus
from agent.execution.planner import ExecutionPlanner
from agent.execution.registry import ToolRegistry
from agent.execution.tool_runtime import ToolRuntime
from agent.recovery import RecoveryClassifier, RecoveryEngine, ResumeCoordinator
from agent.recovery.exceptions import RecoveryErrorBase
from agent.runtime.context import TaskContext
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.run_engine import RunEngine
from agent.runtime.states import RunStatus

from .budget import ExecutionBudget
from .decisions import LoopDecision, StopReason
from .events import (
    BUDGET_EXCEEDED,
    CANCELLATION_REQUESTED,
    ORCHESTRATION_STARTED,
    ORCHESTRATION_STOPPED,
    ORCHESTRATION_RESUMED,
    REPLAN_REQUESTED,
    REPLAN_SKIPPED,
)
from .exceptions import BudgetExceeded, OrchestrationRefused
from .idempotency import DuplicateActionDetector
from .loop import ExecutionLoop
from .models import OrchestrationResult
from .plan_validation import PlanValidator
from .policy import (
    ConservativeRiskPolicy,
    ExecutionPolicy,
    RiskDecision,
    RiskPolicy,
)

_TERMINAL_PLANS = (PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED)


class TaskClassifier:
    """Deterministic classification hook (Sprint 1.0.5).

    Interface only — an autonomous LLM intent router is a LATER sprint.
    The default considers a formed TaskContext ready for planning.
    """

    def classify(self, context: TaskContext) -> bool:
        return bool(context and context.goal)


class RuntimeOrchestrator:
    def __init__(
        self,
        store,
        tool_registry: ToolRegistry,
        planner: Optional[ExecutionPlanner] = None,
        run_engine: Optional[RunEngine] = None,
        engine: Optional[ExecutionEngine] = None,
        risk_policy: Optional[RiskPolicy] = None,
        classifier: Optional[TaskClassifier] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._store = store
        self._registry = tool_registry
        self._clock = clock or utcnow
        self._planner = planner or ExecutionPlanner(clock=self._clock)
        self._run_engine = run_engine or RunEngine(clock=self._clock, store=store)
        if engine is None:
            engine = ExecutionEngine(
                ToolRuntime(tool_registry), store=store, clock=self._clock
            )
        self._engine = engine
        self._risk_policy = risk_policy or ConservativeRiskPolicy()
        self._classifier = classifier or TaskClassifier()
        self._validator = PlanValidator(tool_registry)
        self._detector = DuplicateActionDetector(store)
        self._cancel_flags: Dict[str, bool] = {}

    # ── new run ──────────────────────────────────────────────────────

    def run(
        self,
        task_context: TaskContext,
        policy: Optional[ExecutionPolicy] = None,
        step_specs: Optional[List[Dict[str, Any]]] = None,
    ) -> OrchestrationResult:
        policy = policy or ExecutionPolicy()
        run = self._run_engine.create_run(
            task_type=task_context.metadata.get("task_type", "orchestrated"),
            model_profile=policy.model_profile,
        )
        self._append(ORCHESTRATION_STARTED, run.id,
                     goal=task_context.goal, policy=policy.__dict__)

        self._run_engine.start_run(run)  # CREATED → CLASSIFYING
        if not self._classifier.classify(task_context):
            self._run_engine.fail_run(run, error="classification failed")
            return self._finalize_result(run, None, policy)
        self._run_engine.transition(run, RunStatus.PLANNING)

        plan, plan_error = self._make_plan(run, task_context, step_specs)
        if plan is None:
            self._run_engine.fail_run(run, error=plan_error)
            stop = StopReason.NO_PLAN if "at least one step" in (plan_error or "") \
                else StopReason.INVALID_PLAN
            return self._finalize_result(run, None, policy, stop=stop, error=plan_error)

        self._persist_plan(plan)  # durable BEFORE any step write (FK safety)
        self._run_engine.transition(run, RunStatus.RUNNING)
        return self._drive(run, plan, policy, task_context=task_context)

    # ── resume ───────────────────────────────────────────────────────

    def resume(
        self,
        run_id: str,
        policy: Optional[ExecutionPolicy] = None,
        step_specs: Optional[List[Dict[str, Any]]] = None,
    ) -> OrchestrationResult:
        policy = policy or ExecutionPolicy()
        run = self._store.get_run(run_id)
        if run.status.is_terminal:
            return self._finalize_result(run, None, policy,
                                         stop=_terminal_stop(run.status), error=None)
        self._append(ORCHESTRATION_RESUMED, run.id)

        recovery = RecoveryEngine(self._store, run_engine=self._run_engine,
                                  clock=self._clock)
        disposition = recovery.resume(run_id, engine=None)
        action = disposition.action

        if action == "wait":
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.APPROVAL_REQUIRED,
                                         disposition=disposition.disposition)
        if action == "manual_review":
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.MANUAL_REVIEW_REQUIRED,
                                         disposition=disposition.disposition)
        if action in ("completed", "plan_completed"):
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.COMPLETED,
                                         disposition=disposition.disposition)
        if action == "needs_planning":
            return self._resume_with_plan(run, policy, step_specs,
                                          disposition.disposition)
        # resume_ready / resumed / failed → continue the bounded loop
        plan = self._active_plan(run.id)
        if plan is None:
            return self._resume_with_plan(run, policy, step_specs,
                                          disposition.disposition)
        return self._drive(run, plan, policy,
                           disposition=disposition.disposition)

    def approve(
        self,
        run_id: str,
        approval_id: str,
        policy: Optional[ExecutionPolicy] = None,
    ) -> OrchestrationResult:
        policy = policy or ExecutionPolicy()
        run = self._store.get_run(run_id)
        if run.status.is_terminal:
            # §35: late approval on a cancelled/completed run is refused.
            raise OrchestrationRefused(
                f"run {run_id} is {run.status.value} — approval refused"
            )
        coordinator = ResumeCoordinator(self._store, run_engine=self._run_engine,
                                        clock=self._clock)
        try:
            outcome = coordinator.approve(run_id, approval_id, engine=None)
        except RecoveryErrorBase as exc:
            raise OrchestrationRefused(str(exc)) from exc
        action = outcome.action
        if action in ("resume_ready", "resumed"):
            plan = self._active_plan(run.id)
            if plan is None:
                return self._finalize_result(run, None, policy,
                                             stop=StopReason.NO_PLAN)
            return self._drive(run, plan, policy,
                               disposition=outcome.disposition)
        if action == "completed":
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.COMPLETED)
        if action == "wait":
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.APPROVAL_REQUIRED)
        if action == "manual_review":
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.MANUAL_REVIEW_REQUIRED)
        return self._finalize_result(run, None, policy,
                                     stop=StopReason.EXECUTION_FAILED,
                                     error=f"unexpected recovery outcome: {action}")

    # ── cancellation ─────────────────────────────────────────────────

    def cancel(self, run_id: str) -> OrchestrationResult:
        run = self._store.get_run(run_id)
        if run.status.is_terminal:
            return self._finalize_result(run, None, ExecutionPolicy(),
                                         stop=_terminal_stop(run.status))
        self._cancel_flags[run_id] = True
        self._append(CANCELLATION_REQUESTED, run_id, reason="operator")
        plan = self._active_plan(run_id)
        if plan is not None and not self._tool_in_flight(plan):
            plan = self._engine.cancel_plan(plan)
            self._run_engine.cancel_run(run)
            return self._finalize_result(run, plan, ExecutionPolicy(),
                                         stop=StopReason.CANCELLED)
        return self._finalize_result(
            run, plan, ExecutionPolicy(),
            stop=StopReason.CANCELLED,
            notes=["cancellation requested; finalizing after in-flight tool"],
        )

    # ── replan (infrastructure only) ─────────────────────────────────

    def request_replan(
        self,
        run_id: str,
        reason: str = "",
        step_specs: Optional[List[Dict[str, Any]]] = None,
        task_context: Optional[TaskContext] = None,
        policy: Optional[ExecutionPolicy] = None,
    ) -> OrchestrationResult:
        policy = policy or ExecutionPolicy()
        run = self._store.get_run(run_id)
        if run.status.is_terminal:
            return self._finalize_result(run, None, policy,
                                         stop=_terminal_stop(run.status))
        budget = self._budget(run, policy)
        try:
            budget.check_replan()
        except BudgetExceeded as exc:
            self._append(BUDGET_EXCEEDED, run_id, limit=exc.limit)
            return self._finalize_result(run, None, policy,
                                         stop=budget.stop_reason_for(exc))
        if not policy.allow_replanning:
            self._append(REPLAN_SKIPPED, run_id, reason=reason or "disabled")
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.EXECUTION_FAILED,
                                         error="replanning disabled by policy")
        if step_specs is None or task_context is None:
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.NO_PLAN,
                                         error="step_specs + task_context required for replan")
        self._append(REPLAN_REQUESTED, run_id, reason=reason or "replan")
        # Supersede the old plan (additive — audit history preserved).
        for plan in self._plans_for(run.id):
            if plan.status not in _TERMINAL_PLANS:
                plan.status = PlanStatus.CANCELLED
                self._store.save_plan(plan)
        plan, plan_error = self._make_plan(run, task_context, step_specs)
        if plan is None:
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.INVALID_PLAN,
                                         error=plan_error)
        self._persist_plan(plan)
        return self._finalize_result(
            run, plan, policy, stop=None,
            notes=[f"replan created: {plan.id}; call resume() to continue"],
        )

    # ── read-only ────────────────────────────────────────────────────

    def inspect(self, run_id: str) -> OrchestrationResult:
        run = self._store.get_run(run_id)
        disposition = RecoveryClassifier(self._store).classify_run(run)
        budget = self._budget(run, ExecutionPolicy())
        plans = [p.id for p in self._plans_for(run.id)]
        return OrchestrationResult(
            run_id=run.id,
            status=run.status.value,
            disposition=disposition.value,
            steps_executed=budget.steps,
            tool_calls=budget.tool_calls,
            replans=budget.replans,
            failures=budget.failures,
            approvals=len(self._store.list_approvals(run_id=run.id)),
            started_at=run.started_at.isoformat() if run.started_at else None,
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
            error=run.error,
            notes=[f"plans: {plans}"],
        )

    def dry_run(
        self,
        task_context: TaskContext,
        policy: Optional[ExecutionPolicy] = None,
        step_specs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Pure read/plan preview: ZERO writes, ZERO tool executions."""
        policy = policy or ExecutionPolicy()
        issues: List[str] = []
        plan = None
        try:
            plan = self._planner.create_plan("dry-run", task_context, step_specs or [])
        except InvalidPlan as exc:
            issues.append(str(exc))
        if plan is not None:
            issues.extend(self._validator.validate(plan, task_context))

        steps: List[Dict[str, Any]] = []
        predicted_tools = 0
        if plan is not None and not issues:
            for step in plan.steps:
                metadata = self._registry.metadata(step.tool)
                risk = self._risk_policy.evaluate(step, metadata, task_context)
                effective = (step.requires_approval or metadata.requires_approval
                             or risk is RiskDecision.REQUIRE_APPROVAL)
                if risk is RiskDecision.DENY:
                    execution = "denied"
                elif effective:
                    execution = "requires_approval"
                else:
                    execution = "execute"
                    predicted_tools += 1
                steps.append({
                    "id": step.id,
                    "tool": step.tool,
                    "risk": risk.value,
                    "requires_approval": effective,
                    "execution": execution,
                })
        return {
            "valid": not issues,
            "issues": issues,
            "predicted_steps": len(steps),
            "predicted_tool_calls": predicted_tools,
            "steps": steps,
            "policy": policy.__dict__,
        }

    # ── internals ────────────────────────────────────────────────────

    def _drive(
        self,
        run: AgentRun,
        plan: ExecutionPlan,
        policy: ExecutionPolicy,
        disposition: Optional[str] = None,
        task_context: Optional[TaskContext] = None,
    ) -> OrchestrationResult:
        """Bounded loop + finalization."""
        if run.status in (RunStatus.PLANNING, RunStatus.APPROVED):
            self._run_engine.transition(run, RunStatus.RUNNING)
        budget = self._budget(run, policy)
        try:
            budget.check_time()  # §18/§57: original started_at, across restart
        except BudgetExceeded as exc:
            self._append(BUDGET_EXCEEDED, run.id, limit=exc.limit)
            return self._finalize_result(run, plan, policy,
                                         stop=budget.stop_reason_for(exc),
                                         disposition=disposition)
        loop = ExecutionLoop(
            self._store, self._run_engine, self._engine, self._registry,
            self._detector, self._risk_policy, clock=self._clock,
        )
        outcome = loop.run(
            run, plan, budget, policy,
            task_context if task_context is not None else task_context_for(run, plan),
            cancel_flag=lambda: self._cancel_flags.get(run.id, False),
        )
        if outcome.decision is LoopDecision.BUDGET_EXCEEDED:
            self._append(BUDGET_EXCEEDED, run.id, limit=outcome.stop_reason.value)
        return self._finalize_result(run, plan, policy,
                                     stop=outcome.stop_reason,
                                     disposition=disposition)

    def _make_plan(self, run, task_context, step_specs):
        try:
            plan = self._planner.create_plan(
                run.id, task_context, step_specs or [], plan_id=f"plan-{run.id}"
            )
        except InvalidPlan as exc:
            return None, str(exc)
        issues = self._validator.validate(plan, task_context)
        if issues:
            return None, "; ".join(issues)
        return plan, None

    def _persist_plan(self, plan: ExecutionPlan) -> None:
        """Persist the plan row AND every step row up front.

        The engine only writes steps it touches; a never-started step must
        still be durable so resume sees the FULL plan.
        """
        self._store.save_plan(plan)
        for step in plan.steps:
            self._store.save_step(plan.id, step)

    def _resume_with_plan(self, run, policy, step_specs, disposition):
        if step_specs is None:
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.NO_PLAN,
                                         error="no persisted plan and no step_specs",
                                         disposition=disposition)
        budget = self._budget(run, policy)
        try:
            budget.check_replan()
        except BudgetExceeded as exc:
            return self._finalize_result(run, None, policy,
                                         stop=budget.stop_reason_for(exc),
                                         disposition=disposition)
        if not policy.allow_replanning:
            self._append(REPLAN_SKIPPED, run.id, reason="resume needs plan")
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.EXECUTION_FAILED,
                                         error="replanning disabled by policy",
                                         disposition=disposition)
        from agent.runtime.context import TaskContext

        context = TaskContext(goal=run.task_type, allowed_tools=[])
        plan, plan_error = self._make_plan(run, context, step_specs)
        if plan is None:
            return self._finalize_result(run, None, policy,
                                         stop=StopReason.INVALID_PLAN,
                                         error=plan_error, disposition=disposition)
        self._persist_plan(plan)
        self._append(REPLAN_REQUESTED, run.id, reason="resume replan")
        return self._drive(run, plan, policy, disposition=disposition)

    def _budget(self, run: AgentRun, policy: ExecutionPolicy) -> ExecutionBudget:
        budget = ExecutionBudget(policy, self._store, run.id, clock=self._clock)
        budget.set_started_at(run.started_at)
        return budget

    def _active_plan(self, run_id: str) -> Optional[ExecutionPlan]:
        plans = [p for p in self._plans_for(run_id) if p.status not in _TERMINAL_PLANS]
        return plans[0] if plans else None

    def _plans_for(self, run_id: str) -> List[ExecutionPlan]:
        try:
            return self._store.list_plans(run_id=run_id)
        except TypeError:  # MemoryExecutionStore contract shim
            return [p for p in self._store.list_plans() if p.run_id == run_id]

    @staticmethod
    def _tool_in_flight(plan: ExecutionPlan) -> bool:
        from agent.execution.models import StepStatus

        return any(s.status is StepStatus.RUNNING for s in plan.steps)

    def _finalize_result(
        self,
        run: AgentRun,
        plan: Optional[ExecutionPlan],
        policy: ExecutionPolicy,
        stop: Optional[StopReason] = None,
        error: Optional[str] = None,
        disposition: Optional[str] = None,
        notes: Optional[List[str]] = None,
    ) -> OrchestrationResult:
        budget = self._budget(run, policy)
        self._append(ORCHESTRATION_STOPPED, run.id,
                     stop_reason=stop.value if stop else None,
                     steps=budget.steps, tool_calls=budget.tool_calls,
                     replans=budget.replans, failures=budget.failures)
        return OrchestrationResult(
            run_id=run.id,
            status=run.status.value,
            stop_reason=stop,
            steps_executed=budget.steps,
            tool_calls=budget.tool_calls,
            replans=budget.replans,
            failures=budget.failures,
            approvals=len(self._store.list_approvals(run_id=run.id)),
            started_at=run.started_at.isoformat() if run.started_at else None,
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
            result=run.result if run.status is RunStatus.COMPLETED else None,
            error=error if error is not None else run.error,
            disposition=disposition,
            notes=list(notes or []),
        )

    def _append(self, event_type: str, run_id: str, **payload) -> None:
        event = RuntimeEvent(event_type=event_type, run_id=run_id,
                             timestamp=self._clock(), payload=payload)
        self._store.append_event(event)


def task_context_for(run: AgentRun, plan: ExecutionPlan) -> TaskContext:
    """Rebuild a minimal context for risk evaluation during the loop."""
    return TaskContext(goal=plan.goal, allowed_tools=[s.tool for s in plan.steps])


def _terminal_stop(status: RunStatus) -> StopReason:
    if status is RunStatus.CANCELLED:
        return StopReason.CANCELLED
    if status is RunStatus.COMPLETED:
        return StopReason.COMPLETED
    return StopReason.EXECUTION_FAILED
