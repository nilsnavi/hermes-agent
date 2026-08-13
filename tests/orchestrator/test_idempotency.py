"""Idempotency + duplicate-action tests (Sprint 1.0.5 §31-33)."""

import pytest

from agent.orchestrator.idempotency import (
    DuplicateActionDetector,
    DuplicateStatus,
    compute_input_hash,
    idempotency_key,
)
from agent.orchestrator import ExecutionPolicy, StopReason
from agent.persistence import SQLiteExecutionStore
from agent.runtime.models import AgentRun
from agent.runtime.states import RunStatus

from tests.orchestrator.conftest import T0, make_orchestrator


def _run(store, run_id="run-1"):
    run = AgentRun(id=run_id, task_type="t", status=RunStatus.RUNNING,
                   model_profile="BALANCED", created_at=T0, started_at=T0)
    store.save_run(run)
    return run


def test_idempotency_key_deterministic_and_secret_free():
    h1 = idempotency_key("run-1", "step-1", "abc123")
    h2 = idempotency_key("run-1", "step-1", "abc123")
    assert h1 == h2
    assert len(h1) == 64
    # different step/input → different key
    assert idempotency_key("run-1", "step-2", "abc123") != h1
    assert idempotency_key("run-1", "step-1", "xyz") != h1


def test_input_hash_scrub_before_hash():
    """Sensitive arguments must be scrubbed BEFORE hashing."""
    a = compute_input_hash({"token": "sekrit", "repo": "navitech"})
    b = compute_input_hash({"repo": "navitech", "token": "sekrit"})
    assert a == b  # canonical ordering
    # the hash is of the SCRUBBED payload — cannot leak the secret
    assert "sekrit" not in a


def test_detector_none(store):
    _run(store)
    assert DuplicateActionDetector(store).check("run-1", "s1") is DuplicateStatus.NONE


def test_detector_started_without_completion(store):
    from agent.execution.events import TOOL_STARTED
    from agent.runtime.events import RuntimeEvent

    _run(store)
    store.append_event(RuntimeEvent(event_type=TOOL_STARTED, run_id="run-1",
                                    timestamp=T0, payload={"step": "s1"}))
    assert DuplicateActionDetector(store).check("run-1", "s1") \
        is DuplicateStatus.STARTED_NO_COMPLETION


def test_detector_completed(store):
    from agent.execution.events import TOOL_COMPLETED, TOOL_STARTED
    from agent.runtime.events import RuntimeEvent

    _run(store)
    store.append_event(RuntimeEvent(event_type=TOOL_STARTED, run_id="run-1",
                                    timestamp=T0, payload={"step": "s1"}))
    store.append_event(RuntimeEvent(event_type=TOOL_COMPLETED, run_id="run-1",
                                    timestamp=T0, payload={"step": "s1"}))
    assert DuplicateActionDetector(store).check("run-1", "s1") \
        is DuplicateStatus.COMPLETED


def test_detector_scoped_to_step(store):
    from agent.execution.events import TOOL_COMPLETED
    from agent.runtime.events import RuntimeEvent

    _run(store)
    store.append_event(RuntimeEvent(event_type=TOOL_COMPLETED, run_id="run-1",
                                    timestamp=T0, payload={"step": "s2"}))
    assert DuplicateActionDetector(store).check("run-1", "s1") is DuplicateStatus.NONE


def test_non_idempotent_tool_never_auto_retried(store, registry, clock):
    """Acceptance 12 — timeout-class failure on a non-idempotent tool → fail."""
    calls = {"n": 0}

    def _flaky(args, ctx):
        calls["n"] += 1
        raise RuntimeError("transient")
    registry.register("flaky", _flaky)  # default metadata: NOT idempotent
    orch = make_orchestrator(store, registry, clock)
    from agent.runtime.context import TaskContext

    ctx = TaskContext(goal="t", allowed_tools=["flaky"])
    result = orch.run(ctx, ExecutionPolicy(max_retries=3), [{"name": "s", "tool": "flaky"}])

    assert result.stop_reason is StopReason.EXECUTION_FAILED
    assert calls["n"] == 1


def test_duplicate_action_blocked_and_reused(tmp_path, registry, clock):
    """Acceptance 14 — a step with TOOL_COMPLETED in the journal is not
    executed again; the stored result is reused."""
    from agent.execution.events import TOOL_COMPLETED, TOOL_STARTED
    from agent.execution.models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
    from agent.runtime.events import RuntimeEvent
    from agent.runtime.run_engine import RunEngine

    path = str(tmp_path / "dup.db")
    calls = {"n": 0}

    def _tool(args, ctx):
        calls["n"] += 1
        return {"hits": 1}
    registry.register("search", _tool)

    store = SQLiteExecutionStore(path)
    run_engine = RunEngine(clock=lambda: T0, store=store)
    run = run_engine.create_run("t", "BALANCED", run_id="run-1")
    for target in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING):
        run_engine.transition(run, target)
    plan = ExecutionPlan(id="plan-1", run_id="run-1", goal="g",
                         status=PlanStatus.RUNNING, created_at=T0)
    store.save_plan(plan)
    stored = {"status": "success", "output": {"hits": 1}, "execution_time": 0.1, "error": None}
    store.save_step("plan-1", ExecutionStep(
        id="s1", name="s1", description="", tool="search",
        status=StepStatus.PENDING, result=stored,
    ))
    store.append_event(RuntimeEvent(event_type=TOOL_STARTED, run_id="run-1",
                                    timestamp=T0, payload={"step": "s1"}))
    store.append_event(RuntimeEvent(event_type=TOOL_COMPLETED, run_id="run-1",
                                    timestamp=T0, payload={"step": "s1"}))
    store.close()

    store_b = SQLiteExecutionStore(path)
    orch = make_orchestrator(store_b, registry, clock)
    result = orch.resume("run-1")

    assert result.stop_reason is StopReason.COMPLETED
    assert calls["n"] == 0  # blocked — never executed again
    assert store_b.get_run("run-1").result == {"s1": stored}
    store_b.close()
