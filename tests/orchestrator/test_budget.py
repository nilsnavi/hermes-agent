"""Execution budget tests (Sprint 1.0.5) — journal-derived, restart-safe."""

import pytest

from agent.execution.events import STEP_STARTED, TOOL_FAILED, TOOL_STARTED
from agent.orchestrator import ExecutionBudget
from agent.orchestrator.decisions import StopReason
from agent.orchestrator.events import REPLAN_REQUESTED
from agent.orchestrator.exceptions import BudgetExceeded
from agent.orchestrator.policy import ExecutionPolicy
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.states import RunStatus

from tests.orchestrator.conftest import T0


@pytest.fixture
def run(store):
    run = AgentRun(id="run-1", task_type="t", status=RunStatus.RUNNING,
                   model_profile="BALANCED", created_at=T0, started_at=T0)
    store.save_run(run)
    return run


def _event(event_type, run_id="run-1", step="s1"):
    payload = {"step": step} if "TOOL" in event_type or "STEP" in event_type else {}
    return RuntimeEvent(event_type=event_type, run_id=run_id,
                        timestamp=T0, payload=payload)


def _budget(store, run, policy=None, clock=None):
    budget = ExecutionBudget(policy or ExecutionPolicy(), store, run.id, clock=clock)
    budget.set_started_at(run.started_at)
    return budget


def test_zero_counts_on_fresh_run(store, run, clock):
    budget = _budget(store, run, clock=clock)
    assert (budget.steps, budget.tool_calls, budget.replans, budget.failures) == (0, 0, 0, 0)


def test_counts_derived_from_journal(store, run, clock):
    for i in range(3):
        store.append_event(_event(STEP_STARTED))
    store.append_event(_event(TOOL_STARTED))
    store.append_event(_event(TOOL_FAILED))
    store.append_event(RuntimeEvent(event_type=REPLAN_REQUESTED, run_id="run-1",
                                    timestamp=T0, payload={"reason": "x"}))

    budget = _budget(store, run, clock=clock)
    assert budget.steps == 3
    assert budget.tool_calls == 1
    assert budget.failures == 1
    assert budget.replans == 1


def test_step_limit_raises(store, run, clock):
    for _ in range(ExecutionPolicy().max_steps):
        store.append_event(_event(STEP_STARTED))
    budget = _budget(store, run, clock=clock)
    with pytest.raises(BudgetExceeded) as exc:
        budget.check_step()
    assert exc.value.limit == "steps"
    assert budget.stop_reason_for(exc.value) is StopReason.MAX_STEPS


def test_tool_call_limit_raises(store, run, clock):
    for _ in range(ExecutionPolicy().max_tool_calls):
        store.append_event(_event(TOOL_STARTED))
    budget = _budget(store, run, clock=clock)
    with pytest.raises(BudgetExceeded) as exc:
        budget.check_tool_call()
    assert budget.stop_reason_for(exc.value) is StopReason.MAX_TOOL_CALLS


def test_failure_limit_raises(store, run, clock):
    for _ in range(ExecutionPolicy().max_failures):
        store.append_event(_event(TOOL_FAILED))
    budget = _budget(store, run, clock=clock)
    with pytest.raises(BudgetExceeded) as exc:
        budget.check_failure()
    assert budget.stop_reason_for(exc.value) is StopReason.MAX_FAILURES


def test_replan_limit_raises(store, run, clock):
    for _ in range(ExecutionPolicy().max_replans):
        store.append_event(RuntimeEvent(event_type=REPLAN_REQUESTED, run_id="run-1",
                                        timestamp=T0, payload={}))
    budget = _budget(store, run, clock=clock)
    with pytest.raises(BudgetExceeded) as exc:
        budget.check_replan()
    assert budget.stop_reason_for(exc.value) is StopReason.MAX_REPLANS


def test_runtime_timeout_from_original_started_at(store, run, clock):
    budget = _budget(store, run, clock=clock)
    budget.check_time()  # fresh — passes
    clock.advance(ExecutionPolicy().max_runtime_seconds + 1)
    with pytest.raises(BudgetExceeded) as exc:
        budget.check_time()
    assert budget.stop_reason_for(exc.value) is StopReason.RUNTIME_TIMEOUT


def test_budget_survives_restart(tmp_path, clock):
    """§17/§22 — a new budget instance on the same DB sees the same counts."""
    from agent.persistence import SQLiteExecutionStore

    path = str(tmp_path / "budget.db")
    store_a = SQLiteExecutionStore(path)
    run = AgentRun(id="run-1", task_type="t", status=RunStatus.RUNNING,
                   model_profile="BALANCED", created_at=T0, started_at=T0)
    store_a.save_run(run)
    for _ in range(4):
        store_a.append_event(_event(TOOL_STARTED))
    store_a.close()

    store_b = SQLiteExecutionStore(path)
    budget = _budget(store_b, store_b.get_run("run-1"), clock=clock)
    assert budget.tool_calls == 4  # NOT reset by the new process
    policy = ExecutionPolicy(max_tool_calls=5)
    budget = _budget(store_b, store_b.get_run("run-1"), policy, clock=clock)
    budget.check_tool_call()  # 4 < 5 → one more permitted
    store_b.append_event(_event(TOOL_STARTED))  # 5th call
    with pytest.raises(BudgetExceeded):  # 6th blocked — §53
        budget.check_tool_call()
    store_b.close()


def test_elapsed_zero_without_started_at(store, run, clock):
    run.started_at = None
    store.update_run(run)
    budget = ExecutionBudget(ExecutionPolicy(), store, run.id, clock=clock)
    assert budget.elapsed_seconds == 0.0
    budget.check_time()  # no timeout without a start point
