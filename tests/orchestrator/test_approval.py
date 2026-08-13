"""Approval pause/resume tests (Sprint 1.0.5 §19-21)."""

import pytest

from agent.orchestrator import ExecutionPolicy, StopReason
from agent.orchestrator.exceptions import OrchestrationRefused
from agent.runtime.context import TaskContext

from tests.orchestrator.conftest import make_orchestrator, spec


def _ctx(**kw):
    kwargs = dict(goal="task", allowed_tools=["search", "fetch", "save_draft", "publish"])
    kwargs.update(kw)
    return TaskContext(**kwargs)  # type: ignore[arg-type]


def test_approval_pauses_loop(store, registry, clock):
    """Acceptance 2 — approval pauses the loop; no busy loop."""
    calls = {"publish": 0}
    registry.register("publish", lambda a, c: (calls.__setitem__("publish", calls["publish"] + 1), {"ok": True})[1])
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(),
                      spec("search", "publish", "save_draft"))

    assert result.stop_reason is StopReason.APPROVAL_REQUIRED
    assert result.status == "running"  # run row stays RUNNING (state machine)
    assert result.tool_calls == 1  # only "search" ran
    assert calls["publish"] == 0  # gated tool never called
    approvals = store.list_approvals(run_id=result.run_id)
    assert len(approvals) == 1
    assert approvals[0].step_id == "step-2"


def test_resume_keeps_waiting_without_duplicate(store, registry, clock):
    """Resume while approval is pending → same wait, ONE approval only."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search", "publish"))

    again = orch.resume(result.run_id)
    assert again.stop_reason is StopReason.APPROVAL_REQUIRED
    assert len(store.list_approvals(run_id=result.run_id)) == 1  # no duplicate
    assert store.list_approvals(run_id=result.run_id)[0].step_id == "step-2"


def test_approve_resumes_exactly_once(store, registry, clock):
    """Acceptance 3 — resume after approval continues exactly once."""
    calls = {"publish": 0}
    registry.register("publish", lambda a, c: (calls.__setitem__("publish", calls["publish"] + 1), {"ok": True})[1])
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(),
                      spec("search", "publish", "save_draft"))

    approval = store.list_approvals(run_id=result.run_id)[0]
    final = orch.approve(result.run_id, approval.id)

    assert final.stop_reason is StopReason.COMPLETED
    assert final.tool_calls == 3
    assert calls["publish"] == 1  # EXACTLY once
    assert store.get_run(result.run_id).status.value == "completed"


def test_approve_after_restart(store, registry, clock, tmp_path):
    """§50 — pause at gate, close process, approve+resume from a NEW store."""
    path = str(tmp_path / "restart.db")
    from agent.persistence import SQLiteExecutionStore

    store_a = SQLiteExecutionStore(path)
    orch_a = make_orchestrator(store_a, registry, clock)
    result = orch_a.run(_ctx(), ExecutionPolicy(), spec("search", "publish"))
    assert result.stop_reason is StopReason.APPROVAL_REQUIRED
    approval_id = store_a.list_approvals(run_id=result.run_id)[0].id
    store_a.close()

    # ── Process B ────────────────────────────────────────────────────
    store_b = SQLiteExecutionStore(path)
    calls = {"publish": 0}
    registry.register("publish", lambda a, c: (calls.__setitem__("publish", calls["publish"] + 1), {"ok": True})[1])
    orch_b = make_orchestrator(store_b, registry, clock)

    waiting = orch_b.resume(result.run_id)
    assert waiting.stop_reason is StopReason.APPROVAL_REQUIRED  # same wait

    final = orch_b.approve(result.run_id, approval_id)
    assert final.stop_reason is StopReason.COMPLETED
    assert calls["publish"] == 1
    assert store_b.get_run(result.run_id).status.value == "completed"
    store_b.close()


def test_tool_approval_metadata_overrides_planner(store, registry, clock):
    """Acceptance 16 — tool metadata requires approval even if plan says no."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(),
                      spec("publish"))  # planner: requires_approval NOT set

    assert result.stop_reason is StopReason.APPROVAL_REQUIRED
    assert store.list_approvals(run_id=result.run_id)[0].step_id == "step-1"


def test_planner_approval_flag_is_honored(store, registry, clock):
    """Plan-level requires_approval still gates."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(),
                      spec("search", approval=True))
    assert result.stop_reason is StopReason.APPROVAL_REQUIRED


def test_critical_risk_requires_approval(store, registry, clock):
    """Acceptance 17 — critical context risk gates even a benign tool."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(risk_level="critical"), ExecutionPolicy(), spec("search"))

    assert result.stop_reason is StopReason.APPROVAL_REQUIRED
    assert result.tool_calls == 0  # nothing auto-executed


def test_approval_counted_in_result(store, registry, clock):
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search", "publish"))
    assert result.approvals == 1
