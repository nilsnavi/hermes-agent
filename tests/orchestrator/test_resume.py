"""Resume + restart + budget durability tests (Sprint 1.0.5 §50/§53/§57)."""

from agent.orchestrator import ExecutionPolicy, StopReason
from agent.persistence import SQLiteExecutionStore
from agent.runtime.context import TaskContext

from tests.orchestrator.conftest import make_orchestrator, spec


def _ctx(**kw):
    kwargs = dict(goal="task", allowed_tools=[])
    kwargs.update(kw)
    return TaskContext(**kwargs)  # type: ignore[arg-type]


def _process_a(path, registry, clock, specs, policy=None):
    """Process A: run with a budget that stops it mid-plan, then 'crash'."""
    store = SQLiteExecutionStore(path)
    orch = make_orchestrator(store, registry, clock)
    orch.run(_ctx(), policy or ExecutionPolicy(max_steps=20), specs)
    store.close()


_SIX = spec("search", "fetch", "save_draft", "search", "fetch", "save_draft")


def test_resume_continues_after_restart(tmp_path, registry, clock):
    """§50 — A stops at 3 tool calls; B resumes and completes the plan."""
    path = str(tmp_path / "r.db")
    _process_a(path, registry, clock, _SIX, policy=ExecutionPolicy(max_tool_calls=3))

    store_b = SQLiteExecutionStore(path)
    orch_b = make_orchestrator(store_b, registry, clock)
    run_id = store_b.list_incomplete_runs()[0].id
    result = orch_b.resume(run_id)  # default policy — plenty of headroom

    assert result.stop_reason is StopReason.COMPLETED
    assert result.tool_calls == 6  # 3 in A + 3 in B — exact continuation
    assert store_b.get_run(run_id).status.value == "completed"
    store_b.close()


def test_budget_survives_restart_max_tool_calls(tmp_path, registry, clock):
    """§53 MANDATORY — 4 calls in A, max_tool_calls=5: only 1 more in B."""
    path = str(tmp_path / "r.db")
    _process_a(path, registry, clock, _SIX, policy=ExecutionPolicy(max_tool_calls=4))

    store_b = SQLiteExecutionStore(path)
    orch_b = make_orchestrator(store_b, registry, clock)
    run_id = store_b.list_incomplete_runs()[0].id
    result = orch_b.resume(run_id, policy=ExecutionPolicy(max_tool_calls=5))

    assert result.stop_reason is StopReason.MAX_TOOL_CALLS
    assert result.tool_calls == 5  # 4 from A + exactly 1 in B — 6th blocked
    assert store_b.get_run(run_id).status.value == "running"
    store_b.close()


def test_runtime_timeout_across_restart(tmp_path, registry, clock):
    """§18/§57 — elapsed counts from the ORIGINAL started_at, not process B."""
    path = str(tmp_path / "r.db")
    _process_a(path, registry, clock, _SIX, policy=ExecutionPolicy(max_tool_calls=4))

    store_b = SQLiteExecutionStore(path)
    orch_b = make_orchestrator(store_b, registry, clock)
    run_id = store_b.list_incomplete_runs()[0].id
    clock.advance(1000)  # far beyond the 300s policy
    result = orch_b.resume(run_id, policy=ExecutionPolicy(max_runtime_seconds=300))

    assert result.stop_reason is StopReason.RUNTIME_TIMEOUT
    assert result.tool_calls == 4  # NO further execution
    assert store_b.get_run(run_id).status.value == "running"
    store_b.close()


def test_steps_executed_survive_restart(tmp_path, registry, clock):
    """§16/§22 — step counter is durable: max_steps=4 already consumed in A."""
    path = str(tmp_path / "r.db")
    _process_a(path, registry, clock, _SIX, policy=ExecutionPolicy(max_tool_calls=4))

    store_b = SQLiteExecutionStore(path)
    orch_b = make_orchestrator(store_b, registry, clock)
    run_id = store_b.list_incomplete_runs()[0].id
    result = orch_b.resume(run_id, policy=ExecutionPolicy(max_steps=4))

    assert result.stop_reason is StopReason.MAX_STEPS
    assert result.steps_executed == 4
    store_b.close()


def test_completed_run_resume_is_terminal(tmp_path, registry, clock):
    path = str(tmp_path / "r.db")
    store = SQLiteExecutionStore(path)
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search"))
    assert result.stop_reason is StopReason.COMPLETED
    store.close()

    store_b = SQLiteExecutionStore(path)
    orch_b = make_orchestrator(store_b, registry, clock)
    final = orch_b.resume(result.run_id)
    assert final.stop_reason is StopReason.COMPLETED
    assert final.tool_calls == 1
    store_b.close()
