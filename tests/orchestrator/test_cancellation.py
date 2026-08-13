"""Cancellation tests (Sprint 1.0.5 §34-36)."""

import pytest

from agent.orchestrator import ExecutionPolicy, StopReason
from agent.orchestrator.exceptions import OrchestrationRefused
from agent.runtime.context import TaskContext
from agent.runtime.states import RunStatus

from tests.orchestrator.conftest import make_orchestrator, spec


def _ctx(**kw):
    kwargs = dict(goal="task", allowed_tools=[])
    kwargs.update(kw)
    return TaskContext(**kwargs)  # type: ignore[arg-type]


def test_cancel_while_waiting_approval(store, registry, clock):
    """Acceptance 18 — cancel at the approval gate is allowed."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search", "publish"))
    assert result.stop_reason is StopReason.APPROVAL_REQUIRED

    cancelled = orch.cancel(result.run_id)

    assert cancelled.stop_reason is StopReason.CANCELLED
    assert store.get_run(result.run_id).status is RunStatus.CANCELLED
    assert "CANCELLATION_REQUESTED" in [
        e.event_type for e in store.list_events(run_id=result.run_id)]


def test_cancelled_run_never_resumes(store, registry, clock):
    """Acceptance 19 — resume on a cancelled run is terminal, no execution."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search", "publish"))
    orch.cancel(result.run_id)

    again = orch.resume(result.run_id)
    assert again.stop_reason is StopReason.CANCELLED
    assert again.status == "cancelled"
    assert again.tool_calls == 1  # nothing new executed


def test_late_approve_on_cancelled_run_refused(store, registry, clock):
    """§35 MANDATORY — approval cannot revive a cancelled run."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search", "publish"))
    approval_id = store.list_approvals(run_id=result.run_id)[0].id
    orch.cancel(result.run_id)

    with pytest.raises(OrchestrationRefused):
        orch.approve(result.run_id, approval_id)
    assert store.get_run(result.run_id).status is RunStatus.CANCELLED


def test_cancel_idempotent(store, registry, clock):
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search", "publish"))
    orch.cancel(result.run_id)
    second = orch.cancel(result.run_id)
    assert second.stop_reason is StopReason.CANCELLED


def test_cancel_mid_tool_cooperative(store, registry, clock):
    """§36 — a tool in flight is not magically interrupted; the loop
    finalizes the cancellation cooperatively after the call returns."""
    calls = {"n": 0}
    orch_ref = {}

    def _slow(args, ctx):
        calls["n"] += 1
        orch_ref["orch"].cancel(ctx["run_id"])  # operator cancels mid-tool
        return {"done": True}

    from agent.execution.registry import ToolMetadata, SideEffectClass

    registry.register("slow", _slow,
                      metadata=ToolMetadata(side_effect_class=SideEffectClass.REVERSIBLE_WRITE))
    orch = make_orchestrator(store, registry, clock)
    orch_ref["orch"] = orch
    result = orch.run(_ctx(), ExecutionPolicy(), spec("slow"))

    assert result.stop_reason is StopReason.CANCELLED
    assert calls["n"] == 1  # the in-flight call completed; no second call
    assert store.get_run(result.run_id).status is RunStatus.CANCELLED
