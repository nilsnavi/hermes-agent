"""Approval service (Sprint 1.0.6.3 §22-37) — operator-level decisions.

Sits ON TOP of the durable ``agent_v2_approvals`` rows + the existing
store (never re-implements ApprovalManager / ResumeCoordinator). Every
decision is:

- run-scoped (``approve(run_id, approval_id)`` — the approval must
  belong to the run),
- operator-identity gated (unauthenticated → DENY),
- version-guarded (``expected_version`` → StaleVersionError),
- atomic (approval status + step state + audit event in ONE
  transaction),
- read-only-policy checked (approving an approval whose tool is not
  READ_ONLY → POLICY_DENIED, regardless of operator).

Contract guarantees:

- double approve → exactly one winner (ApprovalAlreadyDecidedError);
- approve on cancelled/completed run → RunTerminalError;
- approve on expired approval → ApprovalExpiredError (status becomes
  EXPIRED — never approved);
- reject → no tool execution, durable events;
- expire → idempotent, repeated expire mutates nothing.
"""

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from agent.execution.approval import ApprovalStatus
from agent.execution.events import STEP_APPROVED, STEP_REJECTED
from agent.execution.exceptions import ConcurrentUpdateError
from agent.execution.models import StepStatus
from agent.persistence import SQLiteExecutionStore
from agent.runtime.events import RuntimeEvent

from .events import APPROVAL_APPROVED, APPROVAL_EXPIRED, APPROVAL_REJECTED, APPROVAL_VIEWED
from .exceptions import (
    ApprovalAlreadyDecidedError,
    ApprovalExpiredError,
    ApprovalNotFound,
    ApprovalScopeMismatch,
    PolicyDeniedError,
    RunTerminalError,
    StaleVersionError,
    UnauthorizedOperator,
)
from .models import ApprovalDecision, DecisionReasonCode, OperatorIdentity
from .run_inspector import RunInspector
from .serializers import sanitize_note

#: Side-effect classes an operator decision may ever permit.
_ALLOWED_SIDE_EFFECTS = ("read_only",)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalService:
    """Operator-level approval controller over the durable store."""

    def __init__(
        self,
        db_path: str,
        clock: Optional[Callable[[], datetime]] = None,
        tool_side_effect_fn: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self._db = db_path
        self._clock = clock or _utcnow
        # Callable(tool_name) -> side_effect_class value ("read_only", ...)
        # or None when unknown. Default: conservative — unknown = not
        # read-only → decision denied.
        self._side_effect = tool_side_effect_fn or (lambda name: None)
        self._inspector = RunInspector(db_path)

    # ── reads ────────────────────────────────────────────────────────

    def list_pending(self) -> List[Any]:
        """Pending approvals (safe views, no raw payloads)."""
        return self._inspector.get_waiting_approvals()

    def get(self, approval_id: str, run_id: Optional[str] = None) -> Any:
        view = self._inspector.get_approval(approval_id)
        if run_id is not None and view.run_id != run_id:
            raise ApprovalScopeMismatch(approval_id, run_id)
        return view

    # ── decisions ────────────────────────────────────────────────────

    def approve(
        self,
        run_id: str,
        approval_id: str,
        operator: OperatorIdentity,
        expected_version: Optional[int] = None,
        note: Optional[str] = None,
        audit_view: bool = False,
    ) -> ApprovalDecision:
        """Atomic PENDING → APPROVED (+ step READY + audit event)."""
        return self._decide(
            run_id, approval_id, operator,
            target=ApprovalStatus.APPROVED,
            reason_code=DecisionReasonCode.OPERATOR_APPROVED,
            event_type=APPROVAL_APPROVED,
            expected_version=expected_version,
            note=note,
            audit_view=audit_view,
            set_step_ready=True,
        )

    def reject(
        self,
        run_id: str,
        approval_id: str,
        operator: OperatorIdentity,
        expected_version: Optional[int] = None,
        note: Optional[str] = None,
        audit_view: bool = False,
    ) -> ApprovalDecision:
        """Atomic PENDING → REJECTED (step SKIPPED, NO tool execution)."""
        return self._decide(
            run_id, approval_id, operator,
            target=ApprovalStatus.REJECTED,
            reason_code=DecisionReasonCode.OPERATOR_REJECTED,
            event_type=APPROVAL_REJECTED,
            expected_version=expected_version,
            note=note,
            audit_view=audit_view,
            set_step_ready=False,
        )

    def expire(
        self,
        approval_id: str,
        run_id: Optional[str] = None,
        operator: Optional[OperatorIdentity] = None,
        expected_version: Optional[int] = None,
    ) -> ApprovalDecision:
        """PENDING → EXPIRED. Idempotent: repeated expire mutates nothing."""
        view = self._inspector.get_approval(approval_id)
        if run_id is not None and view.run_id != run_id:
            raise ApprovalScopeMismatch(approval_id, run_id)
        if view.status != ApprovalStatus.PENDING.value:
            raise ApprovalAlreadyDecidedError(approval_id, view.status)
        operator = operator or self._system_operator()
        self._require_authenticated(operator)
        return self._write_decision(
            run_id=view.run_id,
            approval_id=approval_id,
            operator=operator,
            target=ApprovalStatus.EXPIRED,
            reason_code=DecisionReasonCode.EXPIRED,
            event_type=APPROVAL_EXPIRED,
            expected_version=expected_version,
            note=None,
            set_step_ready=False,
        )

    # ── dry run (§39) ────────────────────────────────────────────────

    def dry_run(
        self,
        run_id: str,
        approval_id: str,
        operator: OperatorIdentity,
        action: str = "approve",
    ) -> Dict[str, Any]:
        """ZERO writes: show run/approval/current state/expected transition/
        policy result. Used by ``approve --dry-run`` / ``reject --dry-run``."""
        view = self._inspector.get_approval(approval_id)
        if view.run_id != run_id:
            raise ApprovalScopeMismatch(approval_id, run_id)
        run = self._inspector.get_run(run_id)
        policy_result = self._policy_result(view, run.status)
        return {
            "run_id": run_id,
            "run_status": run.status,
            "approval_id": approval_id,
            "approval_status": view.status,
            "approval_version": view.version,
            "tool": view.tool,
            "side_effect": view.side_effect or self._side_effect(view.tool),
            "action": action,
            "expected_transition": (
                f"{view.status} -> approved" if action == "approve"
                else f"{view.status} -> rejected"
            ),
            "operator": operator.to_dict(),
            "policy_result": policy_result,
            "writes": 0,
        }

    # ── internals ────────────────────────────────────────────────────

    def _decide(
        self,
        run_id: str,
        approval_id: str,
        operator: OperatorIdentity,
        target: ApprovalStatus,
        reason_code: DecisionReasonCode,
        event_type: str,
        expected_version: Optional[int],
        note: Optional[str],
        audit_view: bool,
        set_step_ready: bool,
    ) -> ApprovalDecision:
        self._require_authenticated(operator)
        view = self._inspector.get_approval(approval_id)
        if view.run_id != run_id:
            raise ApprovalScopeMismatch(approval_id, run_id)
        if view.status != ApprovalStatus.PENDING.value:
            raise ApprovalAlreadyDecidedError(approval_id, view.status)
        if self._is_expired(view):
            # Decide as EXPIRED — never approve/reject an overdue request.
            decision = self._write_decision(
                run_id=run_id, approval_id=approval_id,
                operator=operator, target=ApprovalStatus.EXPIRED,
                reason_code=DecisionReasonCode.EXPIRED,
                event_type=APPROVAL_EXPIRED,
                expected_version=expected_version, note=None,
                set_step_ready=False,
            )
            raise ApprovalExpiredError(approval_id) from None
        run = self._inspector.get_run(run_id)
        if run.status in ("completed", "failed", "cancelled"):
            raise RunTerminalError(run_id, run.status)
        if expected_version is not None and expected_version != view.version:
            raise StaleVersionError(approval_id, expected_version, view.version)
        self._check_policy(view, run.status)
        return self._write_decision(
            run_id=run_id, approval_id=approval_id, operator=operator,
            target=target, reason_code=reason_code, event_type=event_type,
            expected_version=expected_version, note=note,
            set_step_ready=set_step_ready, audit_view=audit_view,
        )

    def _write_decision(
        self,
        run_id: str,
        approval_id: str,
        operator: OperatorIdentity,
        target: ApprovalStatus,
        reason_code: DecisionReasonCode,
        event_type: str,
        expected_version: Optional[int],
        note: Optional[str],
        set_step_ready: bool,
        audit_view: bool = False,
    ) -> ApprovalDecision:
        view = self._inspector.get_approval(approval_id)
        if expected_version is not None and expected_version != view.version:
            raise StaleVersionError(approval_id, expected_version, view.version)
        store = SQLiteExecutionStore(self._db)
        try:
            request = store.get_approval(approval_id)
            if request.status is not ApprovalStatus.PENDING:
                raise ApprovalAlreadyDecidedError(
                    approval_id, request.status.value
                )
            request.status = target
            request.decided_by = operator.operator_id
            request.decision_source = operator.source
            request.decision_reason_code = reason_code.value
            now = self._clock()
            decided_at = now.isoformat()
            events: List[RuntimeEvent] = []
            if audit_view:
                events.append(RuntimeEvent(
                    event_type=APPROVAL_VIEWED, run_id=run_id,
                    timestamp=now, payload={
                        "approval": approval_id, "operator": operator.operator_id,
                        "decision_source": operator.source,
                    },
                ))
            waiting = self._waiting_step(store, run_id, request.step_id)
            if set_step_ready and waiting is not None:
                plan, step = waiting
                step.status = StepStatus.READY
                step_plan_id: Optional[str] = plan.id
                step_to_save = step
                events.append(RuntimeEvent(
                    event_type=STEP_APPROVED, run_id=run_id,
                    timestamp=now, payload={
                        "step": request.step_id,
                        "approval": approval_id,
                    },
                ))
            else:
                step_plan_id = None
                step_to_save = None
            with store.transaction():
                store.update_approval(request, expected_version=expected_version)
                if step_plan_id is not None and step_to_save is not None:
                    store.save_step(step_plan_id, step_to_save)
                elif not set_step_ready and waiting is not None:
                    plan, step = waiting
                    step.status = StepStatus.SKIPPED
                    store.save_step(plan.id, step)
                    events.append(RuntimeEvent(
                        event_type=STEP_REJECTED, run_id=run_id,
                        timestamp=now, payload={
                            "step": request.step_id,
                            "approval": approval_id,
                            "reason_code": reason_code.value,
                        },
                    ))
                events.append(RuntimeEvent(
                    event_type=event_type, run_id=run_id, timestamp=now,
                    payload={
                        "approval": approval_id,
                        "step": request.step_id,
                        "operator": operator.operator_id,
                        "decision_source": operator.source,
                        "reason_code": reason_code.value,
                        "note": sanitize_note(note),
                    },
                ))
                for event in events:
                    store.append_event(event)
            return ApprovalDecision(
                approval_id=approval_id,
                run_id=run_id,
                step_id=request.step_id,
                decision=target.value,
                reason_code=reason_code.value,
                decided_by=operator.operator_id,
                decision_source=operator.source,
                decided_at=decided_at,
                version=view.version + 1,
            )
        finally:
            store.close()

    # ── helpers ──────────────────────────────────────────────────────

    def _waiting_step(
        self, store, run_id: str, step_id: str
    ) -> Optional[tuple]:
        """(plan, step) whose step is in WAITING_APPROVAL (active plan)."""
        from agent.execution.models import PlanStatus

        for plan in store.list_plans(run_id=run_id):
            if plan.status in (PlanStatus.COMPLETED, PlanStatus.FAILED,
                               PlanStatus.CANCELLED):
                continue
            step = plan.step(step_id)
            if step is not None and step.status is StepStatus.WAITING_APPROVAL:
                return plan, step
        return None

    def _check_policy(self, view, run_status: str) -> None:
        """§25: only READ_ONLY staged requests may ever be approved."""
        side_effect = view.side_effect or self._side_effect_of(view.tool)
        if side_effect not in _ALLOWED_SIDE_EFFECTS:
            raise PolicyDeniedError(
                f"tool {view.tool!r} side-effect {side_effect!r} is not "
                f"read-only — approval denied by canary policy"
            )

    def _policy_result(self, view, run_status: str) -> Dict[str, Any]:
        side_effect = view.side_effect or self._side_effect_of(view.tool)
        if run_status in ("completed", "failed", "cancelled"):
            return {"allowed": False, "reason": f"run is {run_status}"}
        if side_effect not in _ALLOWED_SIDE_EFFECTS:
            return {"allowed": False,
                    "reason": f"tool {view.tool!r} is not read-only"}
        return {"allowed": True, "reason": "read-only staged request"}

    def _side_effect_of(self, tool: Optional[str]) -> Optional[str]:
        if not tool:
            return None
        return self._side_effect(tool)

    def _is_expired(self, view) -> bool:
        if not view.expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(view.expires_at)
        except ValueError:
            return False
        return self._clock() > expiry

    @staticmethod
    def _require_authenticated(operator: OperatorIdentity) -> None:
        if operator is None or not operator.authenticated or not operator.operator_id:
            raise UnauthorizedOperator(
                "operator identity is required and must be authenticated"
            )

    @staticmethod
    def _system_operator() -> OperatorIdentity:
        return OperatorIdentity(
            operator_id="system", source="system", authenticated=True,
            roles=frozenset({"system"}),
        )
