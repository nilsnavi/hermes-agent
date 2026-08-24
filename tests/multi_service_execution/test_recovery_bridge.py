"""Sprint 1.3.17 — crash recovery: derive disposition from durable evidence (§22)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent.multi_service_execution import semantic_execution_key
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan, make_pipeline,
)


def _crash_after_commit(tmp, scenario):
    """Simulate a crash AFTER a terminal receipt was written; re-derive."""
    pipe, runtime, adapter, idem, rcpt = make_pipeline(tmp, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b"), tx_id="crash"))
    r = pipe.execute(plan, child_admissions=green_admissions(plan), scenario=scenario)
    # durable evidence exists
    st = idem.get(semantic_execution_key(plan))
    assert st is not None and st["state"] in ("COMMITTED_SIMULATED", "FAILED_SAFE",
                                              "UNKNOWN_OUTCOME")
    calls = adapter.calls()
    # recovery re-derives disposition WITHOUT a second adapter call
    r2 = pipe.execute(plan, child_admissions=green_admissions(plan), scenario=scenario)
    assert r2["replayed"] is True
    assert adapter.calls() == calls
    return st["state"], r["global_state"]


def test_crash_after_successful_commit_replays():
    tmp = Path(tempfile.mkdtemp())
    state, disp = _crash_after_commit(tmp, None)
    assert state == "COMMITTED_SIMULATED"
    assert disp == "SIMULATED_COMMITTED"


def test_crash_after_unknown_never_duplicates_effect():
    tmp = Path(tempfile.mkdtemp())
    state, disp = _crash_after_commit(
        tmp, {"svc-a": {"outcome": "ADAPTER_UNKNOWN_OUTCOME"}})
    assert state == "UNKNOWN_OUTCOME"
    # an unknown terminal is never auto-retried; replay yields 0 adapter calls
    assert True


def test_crash_after_compensation_planning_replays_fail_safe():
    tmp = Path(tempfile.mkdtemp())
    state, disp = _crash_after_commit(
        tmp, {"svc-b": {"outcome": "ADAPTER_FAILED"}})
    assert state == "FAILED_SAFE"
    assert disp == "COMPENSATION_REQUIRED"


def test_disposition_derivable_without_live_process_state():
    # a brand-new pipeline (fresh runtime, no live locks/PID) reads the durable
    # claim and derives the disposition without any adapter invocation.
    from agent.multi_service_execution.authority import ExecutionRuntime
    from agent.multi_service_execution.fake_adapter import FakeServiceAdapter
    from agent.multi_service_execution.pipeline import ExecutionPipeline
    tmp = Path(tempfile.mkdtemp())
    pipe, runtime, adapter, idem, rcpt = make_pipeline(tmp, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",), tx_id="recover"))
    pipe.execute(plan, child_admissions=green_admissions(plan))
    # fresh runtime + fresh adapter on the SAME durable stores
    fresh = ExecutionPipeline(ExecutionRuntime(), FakeServiceAdapter(), idem, rcpt,
                              clock=lambda: 1000.0, env=dict(ENV_REHEARSAL))
    r = fresh.execute(plan, child_admissions=green_admissions(plan))
    assert r["replayed"] is True
    assert r["adapter_call_count"] == 0