"""Execution engine + memory store (Sprint 1.0.2 / 1.0.3).

Orchestrates plan execution: STEP READY → CHECK APPROVAL → RUN TOOL →
SAVE RESULT → VERIFY → NEXT STEP → COMPLETE. Execution pauses at approval
gates (WAITING_APPROVAL) and resumes via approve/reject. All events flow
through the shared RuntimeEvent audit trail.

Sprint 1.0.3: the engine persists every state change through an injected
store (default MemoryExecutionStore; SQLiteExecutionStore for durability).
Each commit groups step + approval + event into ONE transaction boundary —
no write transaction is ever held across an external tool call.
"""

from contextlib import contextmanager
from typing import (
    Any,
    ContextManager,
    Dict,
    Iterator,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

from agent.persistence.redaction import (
    compute_input_hash,
    compute_output_hash,
    idempotency_key,
)
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.states import RunStatus

from .approval import ApprovalManager, ApprovalRequest
from .events import (
    EXECUTION_COMPLETED,
    PLAN_CREATED,
    STEP_APPROVED,
    STEP_REJECTED,
    STEP_STARTED,
    STEP_WAITING_APPROVAL,
    TOOL_COMPLETED,
    TOOL_FAILED,
    TOOL_STARTED,
    Clock,
    emit,
    utcnow,
)
from .exceptions import (
    ExecutionErrorBase,
    ToolNotAllowed,
)
from .models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
from .tool_runtime import ToolRuntime
from .verifier import ExecutionVerifier


@runtime_checkable
class ExecutionStore(Protocol):
    """Durable-store contract consumed by the ExecutionEngine (Sprint 1.0.3).

    Implemented by MemoryExecutionStore and SQLiteExecutionStore.
    """

    def transaction(self) -> ContextManager[None]: ...

    def save_plan(self, plan: ExecutionPlan) -> None: ...

    def save_step(self, plan_id: str, step: ExecutionStep) -> None: ...

    def save_approval(self, request: ApprovalRequest) -> None: ...

    def append_event(self, event: RuntimeEvent, **kwargs: Any) -> int: ...


class MemoryExecutionStore:
    """ExecutionStore contract — in-memory backend (Sprint 1.0.3: SQLite).

    Contract surface (mirrored by SQLiteExecutionStore):
      plans:   save_plan / get_plan / update_step / save_step / get_step / list_plans
      runs:    save_run / get_run / update_run / list_incomplete_runs
      approval:save_approval / get_approval / update_approval / list_approvals
      events:  append_event / list_events
      atomic:  transaction()  (no-op here; SQLite provides a real boundary)

    The memory backend is single-writer by contract: ``update_*`` are plain
    puts (optimistic-concurrency versioning is a SQLite-store concern).
    """

    def __init__(self) -> None:
        self._plans: Dict[str, ExecutionPlan] = {}
        self._steps: Dict[str, Dict[str, ExecutionStep]] = {}
        self._runs: Dict[str, AgentRun] = {}
        self._approvals: Dict[str, ApprovalRequest] = {}
        self._events: List[RuntimeEvent] = []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield  # atomicity is a no-op in memory (single-threaded by contract)

    # ── runs ─────────────────────────────────────────────────────────

    def save_run(self, run: AgentRun) -> None:
        self._runs[run.id] = run

    def get_run(self, run_id: str) -> AgentRun:
        try:
            return self._runs[run_id]
        except KeyError:
            raise ExecutionErrorBase(f"run not found: {run_id}") from None

    def update_run(self, run: AgentRun) -> None:
        if run.id not in self._runs:
            raise ExecutionErrorBase(f"run not found: {run.id}")
        self._runs[run.id] = run

    def list_incomplete_runs(self) -> List[AgentRun]:
        return [
            r for r in self._runs.values()
            if r.status not in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED)
        ]

    # ── plans / steps ────────────────────────────────────────────────

    def save_plan(self, plan: ExecutionPlan) -> None:
        self._plans[plan.id] = plan

    def get_plan(self, plan_id: str) -> ExecutionPlan:
        try:
            return self._plans[plan_id]
        except KeyError:
            raise ExecutionErrorBase(f"plan not found: {plan_id}") from None

    def save_step(self, plan_id: str, step: ExecutionStep) -> None:
        self._steps.setdefault(plan_id, {})[step.id] = step

    def update_step(self, plan_id: str, step: ExecutionStep) -> None:
        if step.id not in self._steps.get(plan_id, {}):
            raise ExecutionErrorBase(f"step not found: {plan_id}/{step.id}")
        self._steps[plan_id][step.id] = step

    def get_step(self, plan_id: str, step_id: str) -> ExecutionStep:
        try:
            return self._steps[plan_id][step_id]
        except KeyError:
            raise ExecutionErrorBase(
                f"step not found: {plan_id}/{step_id}"
            ) from None

    def list_plans(self) -> List[ExecutionPlan]:
        return list(self._plans.values())

    # ── approvals ────────────────────────────────────────────────────

    def save_approval(self, request: ApprovalRequest) -> None:
        self._approvals[request.id] = request

    def get_approval(self, approval_id: str) -> ApprovalRequest:
        try:
            return self._approvals[approval_id]
        except KeyError:
            raise ExecutionErrorBase(
                f"approval not found: {approval_id}"
            ) from None

    def update_approval(self, request: ApprovalRequest) -> None:
        if request.id not in self._approvals:
            raise ExecutionErrorBase(f"approval not found: {request.id}")
        self._approvals[request.id] = request

    def list_approvals(self, run_id: Optional[str] = None) -> List[ApprovalRequest]:
        approvals = list(self._approvals.values())
        if run_id is not None:
            approvals = [a for a in approvals if a.run_id == run_id]
        return approvals

    # ── events ───────────────────────────────────────────────────────

    def append_event(self, event: RuntimeEvent, **kwargs: Any) -> int:
        self._events.append(event)
        return len(self._events)

    def list_events(
        self,
        run_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[RuntimeEvent]:
        events = self._events
        if run_id is not None:
            events = [e for e in events if e.run_id == run_id]
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        if limit is not None:
            events = events[:limit]
        return list(events)


class ExecutionEngine:
    """Runs ExecutionPlans against a ToolRuntime + ApprovalManager."""

    def __init__(
        self,
        tool_runtime: ToolRuntime,
        approval_manager: Optional[ApprovalManager] = None,
        verifier: Optional[ExecutionVerifier] = None,
        store: Optional[ExecutionStore] = None,
        clock: Optional[Clock] = None,
        events: Optional[List[RuntimeEvent]] = None,
    ) -> None:
        self._tools = tool_runtime
        self._approvals = approval_manager or ApprovalManager(clock=clock)
        self._verifier = verifier or ExecutionVerifier()
        # Default: in-memory persistence (Sprint 1.0.2 behavior). Pass a
        # SQLiteExecutionStore for durable persistence.
        self._store: ExecutionStore = (
            store if store is not None else MemoryExecutionStore()
        )
        self._clock = clock or utcnow
        # Steps whose approval gate was passed — bypasses the gate on resume.
        self._approved_steps: set = set()
        # Shared audit trail — pass the RunEngine's list to unify streams.
        self._events: List[RuntimeEvent] = events if events is not None else []

    @property
    def events(self) -> List[RuntimeEvent]:
        return self._events

    @property
    def approvals(self) -> ApprovalManager:
        return self._approvals

    @property
    def store(self) -> ExecutionStore:
        return self._store

    # ── orchestration ────────────────────────────────────────────────

    def execute_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Run every runnable step; pause at approval gates; complete at end.

        Returns the plan in its current state (RUNNING if paused on an
        approval, COMPLETED if finished, FAILED on step failure).
        """
        if plan.status in (PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED):
            raise ExecutionErrorBase(f"plan already terminated: {plan.status.value}")
        event = self._emit(PLAN_CREATED, plan)
        plan.status = PlanStatus.RUNNING
        plan.started_at = plan.started_at or self._clock()
        self._commit(plan, event=event)
        return self._run_to_completion(plan, 0, refuse_running=True)

    def resume_plan(
        self,
        plan: ExecutionPlan,
        approved_step_ids=None,
    ) -> ExecutionPlan:
        """Continue an already-started plan after a process restart.

        Recovery path (Sprint 1.0.4). Unlike :meth:`execute_plan` this
        NEVER re-emits PLAN_CREATED and never resets ``started_at``.
        COMPLETED/SKIPPED steps are skipped. Two refusal cases return the
        plan untouched (no tool is executed):

        - first unfinished step is WAITING_APPROVAL → the plan stays paused
          on its EXISTING approval; no second approval request is created;
        - first unfinished step is RUNNING → the tool outcome is unknown;
          auto-execution would re-run a possibly-completed side effect.
          The caller (recovery) must route this to manual review.

        *approved_step_ids* (iterable of step ids, optional) seeds the
        approval-gate cache with gates that were ALREADY granted in a
        previous process life (persisted APPROVED approvals). Without it a
        fresh engine would re-trigger the gate and create a duplicate
        approval request.

        Raises ExecutionErrorBase for already-terminated plans or an unknown
        (RUNNING) step outcome.
        """
        if plan.status in (PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED):
            raise ExecutionErrorBase(f"plan already terminated: {plan.status.value}")
        if approved_step_ids:
            self._approved_steps.update(
                (plan.id, step_id) for step_id in approved_step_ids
            )
        start = self._next_step_index(plan, 0)
        if start is None:
            start = len(plan.steps)
        return self._run_to_completion(
            plan, start, refuse_waiting=True, refuse_running=True
        )

    def approve_step(self, plan: ExecutionPlan, approval_id: str) -> ExecutionPlan:
        """Approve the pending gate and resume execution from that step."""
        approval = self._approvals.approve(approval_id)  # raises when invalid
        step = plan.step(approval.step_id)
        if step is None or step.status is not StepStatus.WAITING_APPROVAL:
            raise ExecutionErrorBase(
                f"step {approval.step_id} is not waiting for approval"
            )
        self._approved_steps.add((plan.id, step.id))
        event = self._emit(STEP_APPROVED, plan, step=approval.step_id, approval=approval.id)
        # Atomic: approval decision + step state + event in one boundary.
        self._commit(plan, step=step, approval=approval, event=event)
        return self._run_to_completion(plan, plan.steps.index(step))

    def reject_step(self, plan: ExecutionPlan, approval_id: str) -> ExecutionPlan:
        """Reject the gate: the step is skipped and the plan fails closed."""
        approval = self._approvals.reject(approval_id)  # raises when invalid
        event = self._emit(STEP_REJECTED, plan, step=approval.step_id, approval=approval.id)
        step = plan.step(approval.step_id)
        if step is not None:
            step.status = StepStatus.SKIPPED
            step.error = "rejected by user"
            self._skip_remaining(plan, plan.steps.index(step) + 1)
        plan.status = PlanStatus.FAILED
        self._commit(plan, step=step, approval=approval, event=event)
        return plan

    def cancel_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Cancel: every unfinished step is skipped, plan → CANCELLED."""
        for step in plan.steps:
            if step.status not in (StepStatus.COMPLETED, StepStatus.FAILED):
                step.status = StepStatus.SKIPPED
        plan.status = PlanStatus.CANCELLED
        plan.completed_at = self._clock()
        self._commit(plan)
        return plan

    # ── internals ────────────────────────────────────────────────────

    @staticmethod
    def _next_step_index(plan: ExecutionPlan, start: int = 0) -> Optional[int]:
        """Index of the first non-terminal step at/after *start*, or None."""
        for index in range(start, len(plan.steps)):
            if plan.steps[index].status not in (
                StepStatus.COMPLETED, StepStatus.SKIPPED,
            ):
                return index
        return None

    @staticmethod
    def _count_done(plan: ExecutionPlan) -> int:
        return sum(
            1 for s in plan.steps
            if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED, StepStatus.FAILED)
        )

    def execute_next_step(
        self,
        plan: ExecutionPlan,
        start: int = 0,
        approved_step_ids=None,
    ) -> ExecutionPlan:
        """Execute exactly ONE step — the first non-terminal from *start*.

        Public step-granular API for the orchestrator's bounded loop
        (Sprint 1.0.5). Returns the plan; the caller inspects statuses:

        - plan.status COMPLETED → all steps finished (finalization committed);
        - plan.status FAILED → the step failed (TOOL_FAILED committed);
        - plan.status RUNNING:
            * first non-terminal step WAITING_APPROVAL → paused at the gate
              (a duplicate approval request is NEVER created);
            * first non-terminal step RUNNING → tool outcome unknown;
              nothing was executed — caller routes to manual review;
            * otherwise → one step executed; continue the loop.

        COMPLETED/SKIPPED steps are never re-run; a RUNNING step is never
        auto-executed; a WAITING_APPROVAL step with an ungranted gate is
        never executed. *approved_step_ids* seeds gates granted in a
        previous process life (persisted APPROVED approvals).
        """
        if plan.status in (PlanStatus.COMPLETED, PlanStatus.FAILED, PlanStatus.CANCELLED):
            raise ExecutionErrorBase(f"plan already terminated: {plan.status.value}")
        if approved_step_ids:
            self._approved_steps.update(
                (plan.id, step_id) for step_id in approved_step_ids
            )
        index = self._next_step_index(plan, start)
        if index is None:
            # All steps terminal-success → finalize the plan.
            plan.status = PlanStatus.COMPLETED
            plan.completed_at = self._clock()
            event = self._emit(EXECUTION_COMPLETED, plan, steps=len(plan.steps))
            self._commit(plan, event=event)
            return plan
        step = plan.steps[index]
        if step.status is StepStatus.RUNNING:
            return plan  # ambiguous — never auto-execute
        if (
            step.status is StepStatus.WAITING_APPROVAL
            and (plan.id, step.id) not in self._approved_steps
        ):
            return plan  # keep waiting — existing approval preserved
        step.status = StepStatus.RUNNING
        start_event = self._emit(STEP_STARTED, plan, step=step.id, name=step.name)
        if step.requires_approval and (plan.id, step.id) not in self._approved_steps:
            step.status = StepStatus.WAITING_APPROVAL
            approval = self._approvals.request(
                plan.run_id, step.id, reason=step.description or step.name
            )
            wait_event = self._emit(STEP_WAITING_APPROVAL, plan, step=step.id)
            # Atomic: step WAITING_APPROVAL + approval PENDING + BOTH
            # events (STEP_STARTED, STEP_WAITING_APPROVAL) — one boundary.
            self._commit(
                plan, step=step, approval=approval,
                event=[start_event, wait_event],
            )
            return plan  # paused — resume via approve_step / recovery.approve
        self._commit(plan, step=step, event=start_event)
        self._run_step(plan, step)
        return plan

    def _run_to_completion(
        self,
        plan: ExecutionPlan,
        start: int = 0,
        refuse_waiting: bool = False,
        refuse_running: bool = False,
    ) -> ExecutionPlan:
        """Drive ``execute_next_step`` until the plan terminates or stalls.

        *refuse_waiting*: stop before the first ungranted approval gate
        (return the plan paused — no duplicate request). *refuse_running*:
        raise on the first RUNNING step (unknown tool outcome).
        """
        while plan.status is PlanStatus.RUNNING:
            index = self._next_step_index(plan, start)
            if index is None:
                return self.execute_next_step(plan, start)  # finalize
            status = plan.steps[index].status
            if refuse_waiting and status is StepStatus.WAITING_APPROVAL:
                return plan  # keep waiting — existing approval preserved
            if refuse_running and status is StepStatus.RUNNING:
                raise ExecutionErrorBase(
                    f"refusing to execute step {plan.steps[index].id}: "
                    "unknown tool outcome (RUNNING)"
                )
            done_before = self._count_done(plan)
            plan = self.execute_next_step(plan, start)
            if self._count_done(plan) == done_before:
                break  # no progress: paused at a gate or ambiguous step
        return plan

    def _run_step(self, plan: ExecutionPlan, step: ExecutionStep) -> bool:
        """Execute one tool, save + verify the result. False → plan failed.

        Persistence contract: the TOOL_STARTED event + RUNNING status are
        committed BEFORE the tool runs, and the result + TOOL_COMPLETED are
        committed AFTER — no write transaction spans the external call.
        Audit contract (Sprint 1.0.6): every TOOL_* event carries
        ``input_hash`` + ``idempotency_key`` (TOOL_COMPLETED also
        ``output_hash``; TOOL_FAILED also ``error_class``) so a later
        process can prove an action was already performed — hashes of
        SCRUBBED payloads only, never raw secrets.
        """
        input_hash = compute_input_hash(step.arguments)
        key = idempotency_key(plan.run_id, step.id, input_hash)
        event = self._emit(TOOL_STARTED, plan, step=step.id, tool=step.tool,
                           input_hash=input_hash, idempotency_key=key)
        self._commit(plan, step=step, event=event)
        context: Dict[str, Any] = {"run_id": plan.run_id, "goal": plan.goal}
        if step.requires_approval:  # gate passed → approved execution
            context["requires_approval"] = True
            context["approved"] = True
        try:
            result = self._tools.execute(step.tool, step.arguments, context)
        except ToolNotAllowed as exc:
            step.status = StepStatus.FAILED
            step.error = str(exc)
            event = self._emit(
                TOOL_FAILED, plan, step=step.id, status="not_allowed",
                error=str(exc), error_class="not_allowed",
                input_hash=input_hash, idempotency_key=key,
            )
            plan.status = PlanStatus.FAILED
            self._commit(plan, step=step, event=event)
            return False

        if not result.ok:
            step.status = StepStatus.FAILED
            step.error = result.error or result.status
            event = self._emit(
                TOOL_FAILED, plan, step=step.id, status=result.status,
                error=step.error, error_class=result.status,
                input_hash=input_hash, idempotency_key=key,
            )
            plan.status = PlanStatus.FAILED
            self._commit(plan, step=step, event=event)
            return False

        step.result = result.to_dict()
        output_hash = compute_output_hash(step.result)
        event = self._emit(
            TOOL_COMPLETED, plan, step=step.id, execution_time=result.execution_time,
            input_hash=input_hash, output_hash=output_hash, idempotency_key=key,
        )

        problems = self._verifier.issues(step, result)
        if problems:
            step.status = StepStatus.FAILED
            step.error = "; ".join(problems)
            plan.status = PlanStatus.FAILED
            self._commit(plan, step=step, event=event)
            return False

        step.status = StepStatus.COMPLETED
        self._commit(plan, step=step, event=event)
        return True

    def _skip_remaining(self, plan: ExecutionPlan, index: int) -> None:
        for step in plan.steps[index:]:
            if step.status is StepStatus.PENDING:
                step.status = StepStatus.SKIPPED

    def _commit(
        self,
        plan: ExecutionPlan,
        step: Optional[ExecutionStep] = None,
        approval: Optional[ApprovalRequest] = None,
        event: Optional[Any] = None,
    ) -> None:
        """Persist a state change — ONE transaction boundary.

        Grouped writes (step + approval + events) are atomic: a crash inside
        the boundary rolls back all of them (SQLite backend). *event* accepts
        a single RuntimeEvent or a list (multi-event boundaries).
        """
        events = event if isinstance(event, list) else ([event] if event is not None else [])
        with self._store.transaction():
            self._store.save_plan(plan)
            if step is not None:
                self._store.save_step(plan.id, step)
            if approval is not None:
                self._store.save_approval(approval)
            for ev in events:
                self._store.append_event(ev)

    def _emit(self, event_type: str, plan: ExecutionPlan, **payload: Any) -> RuntimeEvent:
        return emit(
            self._events,
            event_type,
            plan.run_id,
            self._clock(),
            plan_id=plan.id,
            **payload,
        )
