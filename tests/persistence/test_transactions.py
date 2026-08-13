"""Transaction-boundary tests (Sprint 1.0.3 §13 / §34).

Grouped writes (step + approval + event) must be atomic: a failure inside
the boundary rolls back everything — no partial state.
"""

import pytest

from agent.execution.approval import ApprovalRequest, ApprovalStatus
from agent.execution.models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
from agent.persistence import SQLiteExecutionStore
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.states import RunStatus
from datetime import datetime, timezone

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = SQLiteExecutionStore(str(tmp_path / "state.db"))
    s.save_run(AgentRun(
        id="run-1", task_type="t", status=RunStatus.RUNNING,
        model_profile="BALANCED", created_at=T0,
    ))
    s.save_plan(ExecutionPlan(
        id="plan-1", run_id="run-1", goal="g", status=PlanStatus.RUNNING, created_at=T0,
    ))
    s.save_step("plan-1", ExecutionStep(
        id="step-1", name="s1", description="", tool="github",
        status=StepStatus.WAITING_APPROVAL,
    ))
    yield s
    s.close()


def _event(event_type="X", run_id="run-1"):
    return RuntimeEvent(event_type=event_type, run_id=run_id, timestamp=T0, payload={})


def test_approval_gate_write_is_atomic(store):
    """step WAITING_APPROVAL + approval PENDING + event — one boundary."""
    approval = ApprovalRequest(
        id="approval-1", run_id="run-1", step_id="step-1", status=ApprovalStatus.PENDING,
        created_at=T0,
    )
    with store.transaction():
        store.save_step("plan-1", store.get_step("plan-1", "step-1"))
        store.save_approval(approval)
        store.append_event(_event("STEP_WAITING_APPROVAL"))
    assert store.get_approval("approval-1").status is ApprovalStatus.PENDING
    assert store.get_step("plan-1", "step-1").status is StepStatus.WAITING_APPROVAL
    assert [e.event_type for e in store.list_events(run_id="run-1")] == [
        "STEP_WAITING_APPROVAL"
    ]


def test_mid_transaction_failure_rolls_back(store):
    """Exception inside the boundary → NOTHING persisted."""
    step = store.get_step("plan-1", "step-1")
    step.status = StepStatus.COMPLETED
    step.result = {"ok": 1}
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.save_step("plan-1", step)
            store.append_event(_event("TOOL_COMPLETED"))
            raise RuntimeError("boom mid-transaction")

    assert store.get_step("plan-1", "step-1").status is StepStatus.WAITING_APPROVAL
    assert store.get_step("plan-1", "step-1").result is None
    assert store.list_events(run_id="run-1") == []


def test_tool_result_and_event_atomic(store):
    """step result + TOOL_COMPLETED event — one boundary (no partial state)."""
    step = store.get_step("plan-1", "step-1")
    step.status = StepStatus.RUNNING
    store.save_step("plan-1", step)
    step.status = StepStatus.COMPLETED
    step.result = {"output": {"rows": 3}}
    with store.transaction():
        store.save_step("plan-1", step)
        store.append_event(_event("TOOL_COMPLETED"))
    loaded = store.get_step("plan-1", "step-1")
    assert loaded.status is StepStatus.COMPLETED
    assert loaded.result == {"output": {"rows": 3}}
    assert [e.event_type for e in store.list_events(run_id="run-1")] == [
        "TOOL_COMPLETED"
    ]


def test_crash_inside_boundary_leaves_no_approval_orphan(store):
    """The §13 nightmare: step=WAITING_APPROVAL but approval row missing.
    A crash INSIDE the boundary must roll back BOTH — never a partial gate."""
    approval = ApprovalRequest(
        id="approval-1", run_id="run-1", step_id="step-1", status=ApprovalStatus.PENDING,
        created_at=T0,
    )
    with pytest.raises(SystemExit):
        with store.transaction():
            store.save_step("plan-1", store.get_step("plan-1", "step-1"))
            store.save_approval(approval)
            raise SystemExit("process died mid-commit")
    with pytest.raises(Exception):
        store.get_approval("approval-1")
