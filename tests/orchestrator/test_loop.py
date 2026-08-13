"""Bounded loop tests (Sprint 1.0.5) — the hard-stop guarantees."""

import pytest

from agent.orchestrator import ExecutionPolicy, StopReason
from agent.runtime.context import TaskContext

from tests.orchestrator.conftest import make_orchestrator, spec


def _ctx(**kw):
    kwargs = dict(goal="task", allowed_tools=[])
    kwargs.update(kw)
    return TaskContext(**kwargs)  # type: ignore[arg-type]


def test_simple_three_step_plan_completes(store, registry, clock):
    """Acceptance 1 — simple 3-step plan completes."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search", "fetch", "save_draft"))

    assert result.status == "completed"
    assert result.stop_reason is StopReason.COMPLETED
    assert result.tool_calls == 3
    assert result.steps_executed == 3
    assert store.get_run(result.run_id).status.value == "completed"
    assert set(store.get_run(result.run_id).result) == {"step-1", "step-2", "step-3"}


def test_loop_emits_orchestration_events(store, registry, clock):
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search"))
    types = [e.event_type for e in store.list_events(run_id=result.run_id)]
    assert "ORCHESTRATION_STARTED" in types
    assert "ORCHESTRATION_STOPPED" in types
    assert types[0] == "RUN_CREATED"
    assert types[-1] == "ORCHESTRATION_STOPPED"


def test_completed_steps_not_rerun(store, registry, clock):
    """Acceptance 4 — resume never re-executes completed steps."""
    calls = {"search": 0}
    from agent.execution.registry import ToolMetadata, SideEffectClass

    registry.register("search", lambda a, c: (calls.__setitem__("search", calls["search"] + 1), {"hits": 1})[1],
                      metadata=ToolMetadata(idempotent=True,
                                            side_effect_class=SideEffectClass.READ_ONLY))
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(), spec("search", "fetch"))

    assert result.stop_reason is StopReason.COMPLETED
    assert calls["search"] == 1
    assert result.tool_calls == 2


def test_max_steps_enforced(store, registry, clock):
    """Acceptance 7 + §54 — a huge plan stops exactly at max_steps."""
    plan = spec(*(["search"] * 100))
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(max_steps=5), plan)

    assert result.stop_reason is StopReason.MAX_STEPS
    assert result.steps_executed == 5
    assert result.tool_calls == 5
    assert store.get_run(result.run_id).status.value == "running"  # not completed


def test_max_tool_calls_enforced(store, registry, clock):
    """Acceptance 8 — tool budget blocks the next call."""
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(max_tool_calls=2),
                      spec("search", "fetch", "save_draft"))

    assert result.stop_reason is StopReason.MAX_TOOL_CALLS
    assert result.tool_calls == 2


def test_max_failures_enforced(store, registry, clock):
    """Acceptance 10 + §56 — retryable failure forever stops at max_failures."""
    calls = {"n": 0}

    def _flaky(args, ctx):
        calls["n"] += 1
        raise RuntimeError("always fails")
    from agent.execution.registry import ToolMetadata, SideEffectClass

    registry.register("flaky", _flaky,
                      metadata=ToolMetadata(idempotent=True,
                                            side_effect_class=SideEffectClass.READ_ONLY))
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(max_failures=3, max_retries=10),
                      spec("flaky"))

    assert result.stop_reason is StopReason.MAX_FAILURES
    assert calls["n"] == 3  # exactly bounded — no infinite retry
    assert store.get_run(result.run_id).status.value == "running"


def test_non_retryable_failure_fails_immediately(store, registry, clock):
    """A non-idempotent failing tool fails the run after ONE attempt."""
    calls = {"n": 0}

    def _boom(args, ctx):
        calls["n"] += 1
        raise RuntimeError("boom")
    registry.register("boom", _boom)  # default metadata: NOT idempotent
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(max_retries=5), spec("boom"))

    assert result.stop_reason is StopReason.EXECUTION_FAILED
    assert calls["n"] == 1  # never auto-retried
    assert store.get_run(result.run_id).status.value == "failed"


def test_idempotent_retry_bounded(store, registry, clock):
    """Acceptance 13 — idempotent tool retries exactly max_retries times."""
    calls = {"n": 0}

    def _flaky(args, ctx):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("transient")
        return {"ok": True}
    from agent.execution.registry import ToolMetadata, SideEffectClass

    registry.register("flaky", _flaky,
                      metadata=ToolMetadata(idempotent=True,
                                            side_effect_class=SideEffectClass.READ_ONLY))
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(max_retries=2, max_failures=5),
                      spec("flaky"))

    assert result.stop_reason is StopReason.COMPLETED
    assert calls["n"] == 3  # 1 initial + 2 retries
    assert store.get_run(result.run_id).result["step-1"]["output"] == {"ok": True}


def test_retry_exhausted_fails(store, registry, clock):
    calls = {"n": 0}

    def _flaky(args, ctx):
        calls["n"] += 1
        raise RuntimeError("still failing")
    from agent.execution.registry import ToolMetadata, SideEffectClass

    registry.register("flaky", _flaky,
                      metadata=ToolMetadata(idempotent=True,
                                            side_effect_class=SideEffectClass.READ_ONLY))
    orch = make_orchestrator(store, registry, clock)
    result = orch.run(_ctx(), ExecutionPolicy(max_retries=1, max_failures=5),
                      spec("flaky"))

    assert result.stop_reason is StopReason.EXECUTION_FAILED
    assert calls["n"] == 2  # 1 initial + exactly 1 retry
    assert store.get_run(result.run_id).status.value == "failed"


def test_performance_smoke(store, registry, clock):
    """§64 — 10-step fake run: orchestration must be ms, not seconds/step."""
    import time

    orch = make_orchestrator(store, registry, clock)
    started = time.perf_counter()
    result = orch.run(_ctx(), ExecutionPolicy(), spec(*(["search"] * 10)))
    elapsed = time.perf_counter() - started

    assert result.stop_reason is StopReason.COMPLETED
    assert result.tool_calls == 10
    assert elapsed < 5.0, f"orchestrator too slow: {elapsed:.2f}s"
