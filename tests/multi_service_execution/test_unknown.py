"""Sprint 1.3.17 — UNKNOWN outcome must never auto-retry (P0)."""

from __future__ import annotations

from agent.multi_service_execution import semantic_execution_key
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan, make_pipeline,
)


def test_unknown_maps_to_unknown_state_not_safe(tmp_path):
    pipeline, runtime, adapter, idem, _ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    scenario = {"svc-b": {"outcome": "ADAPTER_UNKNOWN_OUTCOME"}}
    r = pipeline.execute(plan, child_admissions=green_admissions(plan), scenario=scenario)
    assert r["global_state"] == "EXECUTION_UNKNOWN"
    assert r["global_state"] != "SIMULATED_COMMITTED"
    assert idem.get(semantic_execution_key(plan)) is not None


def test_unknown_stored_terminal_no_auto_retry(tmp_path):
    pipeline, runtime, adapter, idem, _ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    scenario = {"svc-a": {"outcome": "ADAPTER_UNKNOWN_OUTCOME"}}
    pipeline.execute(plan, child_admissions=green_admissions(plan), scenario=scenario)
    calls = adapter.calls()
    dup = pipeline.execute(plan, child_admissions=green_admissions(plan), scenario=scenario)
    # no second adapter invocation: prior UNKNOWN is terminal -> replay
    assert dup["replayed"] is True
    assert adapter.calls() == calls


def test_second_runtime_unknown_does_not_invoke_adapter(tmp_path):
    # a different pipeline (fresh runtime) re-encountering the SAME unknown must
    # not invoke the adapter either: the durable claim is terminal.
    from agent.multi_service_execution.authority import ExecutionRuntime
    from agent.multi_service_execution.fake_adapter import FakeServiceAdapter
    from agent.multi_service_execution.pipeline import ExecutionPipeline
    p1, r1, a1, idem, rcpt = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    scen = {"svc-a": {"outcome": "ADAPTER_UNKNOWN_OUTCOME"}}
    p1.execute(plan, child_admissions=green_admissions(plan), scenario=scen)
    # second runtime sharing the same durable idem store
    p2 = ExecutionPipeline(ExecutionRuntime(), FakeServiceAdapter(), idem, rcpt,
                           clock=lambda: 1000.0, env=dict(ENV_REHEARSAL))
    r2 = p2.execute(plan, child_admissions=green_admissions(plan), scenario=scen)
    assert r2["replayed"] is True
    assert r2["adapter_call_count"] == 0


def test_unknown_recovery_blocks_execution(tmp_path):
    from agent.multi_service_execution.recovery_bridge import recovery_allows_execution
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    allowed, reason = recovery_allows_execution(plan, {"classification": "UNKNOWN_RECOVERY_STATE"})
    assert allowed is False
    assert "recovery" in reason