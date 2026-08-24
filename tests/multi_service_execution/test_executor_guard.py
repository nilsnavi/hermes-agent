"""Sprint 1.3.17 — bounded executor guard: any missing gate -> 0 adapter calls."""

from __future__ import annotations

from agent.multi_service_execution import ExecutionMode
from agent.multi_service_execution.authority import ExecutionRuntime
from agent.multi_service_execution.barrier import ExecutionBarrier
from agent.multi_service_execution.executor import BoundedMultiServiceExecutor
from agent.multi_service_execution.fake_adapter import FakeServiceAdapter
from agent.multi_service_execution.models import GlobalExecutionState
from tests.multi_service_execution.conftest import make_coord_plan, make_exec_plan


def _ctx(tmp_path):
    runtime = ExecutionRuntime()
    adapter = FakeServiceAdapter()
    executor = BoundedMultiServiceExecutor()
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    return runtime, adapter, executor, plan


def _auth(runtime, plan):
    return runtime._issue(plan, now_monotonic=1000.0, ttl_s=1000.0,
                          prepared_token_set=frozenset(plan.service_set),
                          approval_set=frozenset(c.approval_id for c in plan.children),
                          budget_reservations=frozenset(c.budget_reservation_id for c in plan.children),
                          lock_owner_set=frozenset(plan.service_set))


def test_executor_requires_valid_authority(tmp_path):
    runtime, adapter, executor, plan = _ctx(tmp_path)
    foreign = ExecutionRuntime()
    res = executor.execute(foreign, _auth(foreign, plan), plan, adapter, now_monotonic=1000.0)
    assert res.adapter_call_count == 0
    assert res.global_state == GlobalExecutionState.EXECUTION_DENIED


def test_executor_requires_exact_owner(tmp_path):
    runtime, adapter, executor, plan = _ctx(tmp_path)
    auth = _auth(runtime, plan)
    other = ExecutionRuntime()
    res = executor.execute(other, auth, plan, adapter, now_monotonic=1000.0)
    assert res.adapter_call_count == 0
    assert res.global_state == GlobalExecutionState.EXECUTION_DENIED


def test_executor_denied_without_barrier_ready(tmp_path):
    runtime, adapter, executor, plan = _ctx(tmp_path)
    auth = _auth(runtime, plan)
    barrier = ExecutionBarrier().evaluate(
        plan, locks_live_owned=False)  # not ready
    res = executor.execute(runtime, auth, plan, adapter, now_monotonic=1000.0,
                           barrier=barrier)
    assert res.adapter_call_count == 0
    assert res.global_state == GlobalExecutionState.EXECUTION_DENIED


def test_executor_denied_on_child_admission_missing(tmp_path):
    runtime, adapter, executor, plan = _ctx(tmp_path)
    auth = _auth(runtime, plan)
    res = executor.execute(runtime, auth, plan, adapter, now_monotonic=1000.0,
                           child_admissions={"svc-a": True, "svc-b": False})
    assert res.adapter_call_count == 0
    assert res.global_state == GlobalExecutionState.EXECUTION_DENIED


def test_executor_denied_on_system_boundary_deny(tmp_path):
    runtime, adapter, executor, plan = _ctx(tmp_path)
    auth = _auth(runtime, plan)
    res = executor.execute(runtime, auth, plan, adapter, now_monotonic=1000.0,
                           boundary_allow=False)
    assert res.adapter_call_count == 0
    assert res.global_state == GlobalExecutionState.EXECUTION_DENIED


def test_executor_denied_on_drift(tmp_path):
    runtime, adapter, executor, plan = _ctx(tmp_path)
    auth = _auth(runtime, plan)
    res = executor.execute(runtime, auth, plan, adapter, now_monotonic=1000.0,
                           no_drift=False)
    assert res.adapter_call_count == 0
    assert res.global_state == GlobalExecutionState.EXECUTION_DENIED


def test_executor_green_path_runs_all_children_once(tmp_path):
    from tests.multi_service_execution.conftest import green_admissions
    runtime, adapter, executor, plan = _ctx(tmp_path)
    auth = _auth(runtime, plan)
    res = executor.execute(runtime, auth, plan, adapter, now_monotonic=1000.0,
                           child_admissions=green_admissions(plan))
    assert res.adapter_call_count == 2  # both children simulated
    assert res.global_state == GlobalExecutionState.SIMULATED_VERIFYING
    assert adapter.calls() == 2


def test_executor_unknown_outcome_no_retry(tmp_path):
    from tests.multi_service_execution.conftest import green_admissions
    runtime, adapter, executor, plan = _ctx(tmp_path)
    auth = _auth(runtime, plan)
    scenario = {"svc-b": {"outcome": "ADAPTER_UNKNOWN_OUTCOME"}}
    res = executor.execute(runtime, auth, plan, adapter, scenario=scenario,
                           now_monotonic=1000.0,
                           child_admissions=green_admissions(plan))
    assert res.global_state == GlobalExecutionState.EXECUTION_UNKNOWN
    # each child invoked exactly once inside a single execute() call
    assert adapter.calls("tx-1:svc-a:1") == 1
    assert adapter.calls("tx-1:svc-b:1") == 1


def test_executor_plan_mismatch_denied(tmp_path):
    runtime, adapter, executor, plan = _ctx(tmp_path)
    auth = _auth(runtime, plan)
    other_plan = make_exec_plan(make_coord_plan(("svc-a",), tx_id="other"))
    res = executor.execute(runtime, auth, other_plan, adapter, now_monotonic=1000.0)
    assert res.adapter_call_count == 0
    assert res.global_state == GlobalExecutionState.EXECUTION_DENIED


def test_mode_off_has_no_simulated_path(tmp_path):
    runtime, adapter, executor, _ = _ctx(tmp_path)
    plan_off = make_exec_plan(make_coord_plan(("svc-a",)),
                              mode=ExecutionMode.OFF)
    auth = runtime._issue(plan_off, now_monotonic=1000.0, ttl_s=1000.0)
    res = executor.execute(runtime, auth, plan_off, adapter, now_monotonic=1000.0)
    assert res.adapter_call_count == 0
    assert res.global_state == GlobalExecutionState.EXECUTION_DENIED