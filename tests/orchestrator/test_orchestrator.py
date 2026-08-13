"""Orchestrator-level tests (Sprint 1.0.5): dry-run, inspect, contracts."""

import pytest

from agent.orchestrator import ExecutionPolicy, StopReason
from agent.runtime.context import TaskContext

from tests.orchestrator.conftest import make_orchestrator, spec


def _ctx(**kw):
    kwargs = dict(goal="task", allowed_tools=["search", "fetch", "save_draft", "publish"])
    kwargs.update(kw)
    return TaskContext(**kwargs)  # type: ignore[arg-type]


def test_dry_run_executes_zero_tools_and_writes(store, registry, clock):
    """Acceptance 21 — dry-run: ZERO tool calls, ZERO store writes."""
    orch = make_orchestrator(store, registry, clock)
    report = orch.dry_run(_ctx(), ExecutionPolicy(),
                          spec("search", "fetch", "publish"))

    assert report["valid"] is True
    assert report["predicted_steps"] == 3
    assert report["predicted_tool_calls"] == 2  # publish is approval-gated
    assert [s["execution"] for s in report["steps"]] == [
        "execute", "execute", "requires_approval",
    ]
    # zero writes: no runs, no plans, no events in the store
    assert store.list_incomplete_runs() == []
    assert store.list_events() == []


def test_dry_run_invalid_plan_reports_issues(store, registry, clock):
    orch = make_orchestrator(store, registry, clock)
    report = orch.dry_run(_ctx(allowed_tools=["ghost"]), ExecutionPolicy(),
                          [{"name": "s", "tool": "ghost"}])
    assert report["valid"] is False
    assert any("unknown tool" in i for i in report["issues"])
    assert report["predicted_tool_calls"] == 0
    assert store.list_incomplete_runs() == []  # still zero writes


def test_inspect_is_read_only(store, registry, clock):
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search"))
    assert result.stop_reason is StopReason.COMPLETED

    info = orch.inspect(result.run_id)
    assert info.run_id == result.run_id
    assert info.status == "completed"
    assert info.tool_calls == 1
    assert info.steps_executed == 1
    assert info.disposition == "terminal"
    assert info.stop_reason is None  # inspect is not a stop event
    # inspect must not add events
    assert info.steps_executed == len([e for e in store.list_events(run_id=result.run_id)
                                       if e.event_type == "STEP_STARTED"])


def test_result_contract_status_stop_pair(store, registry, clock):
    """§40 — every result explains status + stop_reason."""
    orch = make_orchestrator(store, registry, clock)
    paused = orch.run(_ctx(), ExecutionPolicy(), spec("publish"))
    assert paused.status == "running"
    assert paused.stop_reason is StopReason.APPROVAL_REQUIRED

    failed = orch.run(_ctx(), ExecutionPolicy(max_tool_calls=1),
                      spec("search", "fetch"))
    assert failed.stop_reason is StopReason.MAX_TOOL_CALLS


def test_result_summary_has_no_tool_payloads(store, registry, clock):
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search"))
    summary = result.summary()
    assert summary["run_id"] == result.run_id
    assert summary["stop_reason"] == "completed"
    assert summary["steps"] == 1
    assert "output" not in summary
    assert "payload" not in summary


def test_budget_exceeded_event_written(store, registry, clock):
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(max_tool_calls=1),
                      spec("search", "fetch"))
    assert result.stop_reason is StopReason.MAX_TOOL_CALLS
    types = [e.event_type for e in store.list_events(run_id=result.run_id)]
    assert "BUDGET_EXCEEDED" in types
    assert "ORCHESTRATION_STOPPED" in types


def test_risk_deny_fails_closed(store, registry, clock):
    """A DENY risk decision blocks execution (fail closed)."""
    orch = make_orchestrator(store, registry, clock)
    ctx = _ctx(allowed_tools=["delete"], metadata={"deny_tools": ["delete"]})
    result = orch.run(ctx, ExecutionPolicy(), spec("delete"))

    assert result.stop_reason is StopReason.EXECUTION_FAILED
    assert result.tool_calls == 0
    assert store.get_run(result.run_id).status.value == "failed"


def test_irreversible_write_requires_approval(store, registry, clock):
    """§47/§48 — IRREVERSIBLE_WRITE tool gates even with low risk context."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(allowed_tools=["delete"]), ExecutionPolicy(), spec("delete"))

    assert result.stop_reason is StopReason.APPROVAL_REQUIRED
    assert result.tool_calls == 0
    assert store.list_approvals(run_id=result.run_id)[0].step_id == "step-1"


def test_memory_store_flow(registry, clock):
    """§59 — orchestrator works against the in-memory store for simple flow."""
    from agent.execution.executor import MemoryExecutionStore

    store = MemoryExecutionStore()
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search"))

    assert result.stop_reason is StopReason.COMPLETED
    assert result.tool_calls == 1
    assert store.get_run(result.run_id).status.value == "completed"
