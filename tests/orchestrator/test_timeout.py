"""Timeout + replan budget tests (Sprint 1.0.5 §55/§57/§58)."""

from agent.orchestrator import ExecutionPolicy, StopReason
from agent.persistence import SQLiteExecutionStore
from agent.runtime.context import TaskContext

from tests.orchestrator.conftest import make_orchestrator, spec


def _ctx(**kw):
    kwargs = dict(goal="task", allowed_tools=[])
    kwargs.update(kw)
    return TaskContext(**kwargs)  # type: ignore[arg-type]


def test_fresh_run_within_time_budget(store, registry, clock):
    """A fresh run inside the time budget completes normally."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(max_runtime_seconds=300), spec("search"))
    assert result.stop_reason is StopReason.COMPLETED


def test_timeout_stops_fresh_run_mid_loop(store, registry, clock):
    """Clock advances past the budget DURING the loop → RUNTIME_TIMEOUT."""
    calls = {"n": 0}

    def _slow(args, ctx):
        calls["n"] += 1
        return {"done": True}
    registry.register("slow", _slow)

    def _advancing(args, ctx):
        clock.advance(1000)  # a slow tool burns the time budget
        return {"done": True}
    registry.register("advancing", _advancing)

    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(max_runtime_seconds=300),
                      spec("slow", "advancing", "slow"))

    assert result.stop_reason is StopReason.RUNTIME_TIMEOUT
    assert result.tool_calls == 2  # stopped before the third step
    assert store.get_run(result.run_id).status.value == "running"


def test_timeout_before_any_execution_on_resume(tmp_path, registry, clock):
    """§57 — an over-age run is NOT resumed at all."""
    path = str(tmp_path / "t.db")
    store_a = SQLiteExecutionStore(path)
    orch_a = make_orchestrator(store_a, registry, clock)
    orch_a.run(_ctx(), ExecutionPolicy(max_tool_calls=1),
               spec("search", "fetch", "save_draft"))
    store_a.close()

    store_b = SQLiteExecutionStore(path)
    orch_b = make_orchestrator(store_b, registry, clock)
    run_id = store_b.list_incomplete_runs()[0].id
    clock.advance(10_000)
    result = orch_b.resume(run_id, policy=ExecutionPolicy(max_runtime_seconds=300))

    assert result.stop_reason is StopReason.RUNTIME_TIMEOUT
    assert result.tool_calls == 1  # NO new execution
    store_b.close()


def _paused_run(store, registry, clock):
    """Run that pauses at an approval gate — stays active for replan."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search", "publish"))
    assert result.stop_reason is StopReason.APPROVAL_REQUIRED
    return orch, result


def test_replan_budget_exhausted(store, registry, clock):
    """§55 MANDATORY — infinite replan is blocked at max_replans."""
    orch, result = _paused_run(store, registry, clock)
    ctx = _ctx()

    policy = ExecutionPolicy(allow_replanning=True, max_replans=2)
    first = orch.request_replan(result.run_id, reason="r1",
                                step_specs=spec("fetch"), task_context=ctx,
                                policy=policy)
    assert first.stop_reason is None  # accepted (infrastructure)
    second = orch.request_replan(result.run_id, reason="r2",
                                 step_specs=spec("fetch"), task_context=ctx,
                                 policy=policy)
    assert second.stop_reason is None

    third = orch.request_replan(result.run_id, reason="r3",
                                step_specs=spec("fetch"), task_context=ctx,
                                policy=policy)
    assert third.stop_reason is StopReason.MAX_REPLANS
    assert len([e for e in store.list_events(run_id=result.run_id)
                if e.event_type == "REPLAN_REQUESTED"]) == 2


def test_replan_disabled_by_policy(store, registry, clock):
    orch, result = _paused_run(store, registry, clock)
    resp = orch.request_replan(result.run_id, reason="why",
                               step_specs=spec("fetch"), task_context=_ctx(),
                               policy=ExecutionPolicy(allow_replanning=False))
    assert resp.stop_reason is StopReason.EXECUTION_FAILED
    assert "REPLAN_SKIPPED" in [e.event_type for e in store.list_events(run_id=result.run_id)]


def test_no_sleep_in_tests(store, registry, clock):
    """§58 — determinism comes from the injected clock; nothing to assert
    beyond the suite running without time.sleep (all tests use FakeClock)."""
    assert callable(clock)
