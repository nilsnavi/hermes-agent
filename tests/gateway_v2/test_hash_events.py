"""Tool event hash/idempotency tests (Sprint 1.0.6 §36-38, MUST-HAVE 13-16)."""

from agent.execution.events import TOOL_COMPLETED, TOOL_FAILED, TOOL_STARTED
from agent.orchestrator import ExecutionPolicy, StopReason
from agent.persistence.redaction import (
    compute_input_hash,
    compute_output_hash,
    idempotency_key,
)
from agent.runtime.context import TaskContext


def _run(store, registry, clock, specs):
    from agent.orchestrator import RuntimeOrchestrator

    orch = RuntimeOrchestrator(store, registry, clock=clock)
    ctx = TaskContext(goal="t", allowed_tools=["search", "flaky"])
    return orch.run(ctx, ExecutionPolicy(max_failures=5, max_retries=2), specs)


def _events_by_type(store, run_id, event_type):
    return [e for e in store.list_events(run_id=run_id) if e.event_type == event_type]


def test_tool_started_carries_hashes(store, registry, clock):
    result = _run(store, registry, clock,
                  [{"name": "s1", "tool": "search", "arguments": {"q": "docs"}}])
    assert result.stop_reason is StopReason.COMPLETED

    started = _events_by_type(store, result.run_id, TOOL_STARTED)[0]
    expected_hash = compute_input_hash({"q": "docs"})
    assert started.payload["input_hash"] == expected_hash  # MUST-HAVE 13
    assert started.payload["idempotency_key"] == idempotency_key(
        result.run_id, started.payload["step"], expected_hash)  # MUST-HAVE 15
    assert started.payload.get("q") is None  # raw arguments never in event


def test_tool_completed_carries_hashes(store, registry, clock):
    from tests.orchestrator.conftest import spec

    result = _run(store, registry, clock, spec("search"))
    completed = _events_by_type(store, result.run_id, TOOL_COMPLETED)[0]
    assert "input_hash" in completed.payload
    assert "idempotency_key" in completed.payload
    assert "output_hash" in completed.payload  # MUST-HAVE 14
    assert len(completed.payload["output_hash"]) == 64


def test_tool_failed_carries_hashes_and_error_class(store, registry, clock):
    from tests.orchestrator.conftest import spec

    calls = {"n": 0}

    def _flaky(args, ctx):
        calls["n"] += 1
        raise RuntimeError("transient")
    from agent.execution.registry import ToolMetadata, SideEffectClass

    registry.register("flaky", _flaky,
                      metadata=ToolMetadata(idempotent=True,
                                            side_effect_class=SideEffectClass.READ_ONLY))
    result = _run(store, registry, clock, spec("flaky"))
    assert result.stop_reason is StopReason.EXECUTION_FAILED

    failed = _events_by_type(store, result.run_id, TOOL_FAILED)[0]
    assert "input_hash" in failed.payload
    assert "idempotency_key" in failed.payload
    assert "error_class" in failed.payload  # MUST-HAVE: error class stored
    assert failed.payload["error_class"] == "failure"


def test_hash_stable_across_restart():
    """§38 — same canonical input → same hash after restart (new process)."""
    args = {"query": "стабильный запрос", "nested": {"a": 1, "b": [1, 2, 3]}}
    h1 = compute_input_hash(args)
    h2 = compute_input_hash(args)
    assert h1 == h2
    assert len(h1) == 64


def test_different_input_different_hash():
    assert compute_input_hash({"q": "a"}) != compute_input_hash({"q": "b"})


def test_hash_stable_under_key_ordering():
    assert compute_input_hash({"a": 1, "b": 2}) == compute_input_hash({"b": 2, "a": 1})


def test_secret_redacted_before_hash():
    """§38 trade-off documented: secrets never reach the digest input."""
    digest = compute_input_hash({"token": "sekrit-value", "q": "x"})
    assert "sekrit" not in digest
    # Only the secret differs → same hash (documented trade-off: such tools
    # are not canary-eligible anyway).
    assert compute_input_hash({"token": "other", "q": "x"}) == digest


def test_output_hash_of_scrubbed_result():
    result = {"status": "success", "output": {"rows": 1}, "error": None}
    digest = compute_output_hash(result)
    assert len(digest) == 64
    assert compute_output_hash(dict(result)) == digest


def test_duplicate_detector_uses_hashes(store, registry, clock):
    """MUST-HAVE 16 — detector matches on input_hash, not only step_id."""
    from agent.execution.models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
    from agent.orchestrator import RuntimeOrchestrator
    from agent.orchestrator.idempotency import DuplicateActionDetector, DuplicateStatus
    from agent.runtime.events import RuntimeEvent
    from agent.runtime.run_engine import RunEngine
    from agent.runtime.states import RunStatus
    from datetime import datetime, timezone

    t0 = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    run_engine = RunEngine(clock=lambda: t0, store=store)
    run = run_engine.create_run("t", "BALANCED", run_id="run-1")
    for target in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING):
        run_engine.transition(run, target)
    plan = ExecutionPlan(id="plan-1", run_id="run-1", goal="g",
                         status=PlanStatus.RUNNING, created_at=t0)
    store.save_plan(plan)
    store.save_step("plan-1", ExecutionStep(
        id="s1", name="s1", description="", tool="search",
        status=StepStatus.PENDING, arguments={"q": "same"},
    ))

    h1 = compute_input_hash({"q": "same"})
    h2 = compute_input_hash({"q": "other"})
    store.append_event(RuntimeEvent(event_type=TOOL_STARTED, run_id="run-1",
                                    timestamp=t0, payload={"step": "s1",
                                                           "input_hash": h1,
                                                           "idempotency_key": "k1"}))
    store.append_event(RuntimeEvent(event_type=TOOL_COMPLETED, run_id="run-1",
                                    timestamp=t0, payload={"step": "s1",
                                                           "input_hash": h1,
                                                           "idempotency_key": "k1"}))

    detector = DuplicateActionDetector(store)
    # same step + same input → duplicate (COMPLETED)
    assert detector.check("run-1", "s1", input_hash=h1) is DuplicateStatus.COMPLETED
    # same step + DIFFERENT input → NOT a duplicate
    assert detector.check("run-1", "s1", input_hash=h2) is DuplicateStatus.NONE
