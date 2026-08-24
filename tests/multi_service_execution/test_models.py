"""Sprint 1.3.17 — model semantics (state machines, plans, receipts)."""

from __future__ import annotations

import pytest

from agent.multi_service_execution.models import (
    AdapterOutcome, ChildExecutionState, ExecutionMode, ExecutionReceipt,
    GlobalExecutionState, MultiServiceExecutionPlan, can_transition,
    semantic_execution_key, service_set_hash,
)
from tests.multi_service_execution.conftest import make_coord_plan, make_exec_plan


def test_execution_mode_unknown_maps_off():
    assert ExecutionMode.from_str("garbage") == ExecutionMode.OFF
    assert ExecutionMode.from_str(None) == ExecutionMode.OFF
    assert ExecutionMode.from_str("rehearsal") == ExecutionMode.REHEARSAL
    assert ExecutionMode.REHEARSAL.permits_simulated_execution() is True
    assert ExecutionMode.OFF.permits_simulated_execution() is False
    assert ExecutionMode.CANARY.permits_simulated_execution() is False


def test_global_state_machine_only_legal_transitions():
    cp = make_coord_plan(("svc-a",))
    plan = make_exec_plan(cp)
    assert isinstance(plan, MultiServiceExecutionPlan)
    # legal happy path
    assert can_transition(GlobalExecutionState.EXECUTION_CREATED,
                          GlobalExecutionState.EXECUTION_REVALIDATING)
    assert can_transition(GlobalExecutionState.SIMULATED_COMMIT_READY,
                          GlobalExecutionState.SIMULATED_COMMITTED)
    # illegal: created -> committed directly, or re-enter terminal
    assert not can_transition(GlobalExecutionState.EXECUTION_CREATED,
                              GlobalExecutionState.SIMULATED_COMMITTED)
    assert not can_transition(GlobalExecutionState.SIMULATED_COMMITTED,
                              GlobalExecutionState.SIMULATED_VERIFYING)


def test_terminal_states_immutable():
    for s in (GlobalExecutionState.SIMULATED_COMMITTED,
              GlobalExecutionState.EXECUTION_DENIED,
              GlobalExecutionState.MANUAL_REVIEW_REQUIRED):
        # no outgoing edges from a terminal state
        assert not can_transition(s, GlobalExecutionState.SIMULATED_EXECUTING)


def test_plan_is_frozen_and_hash_stable():
    cp = make_coord_plan(("svc-a", "svc-b"))
    plan = make_exec_plan(cp)
    with pytest.raises(Exception):
        plan.service_set = ("hacked",)  # frozen
    assert plan.plan_hash() == plan.plan_hash()  # deterministic


def test_plan_drift_changes_hash():
    p1 = make_exec_plan(make_coord_plan(("svc-a",), tx_id="t1"))
    p2 = make_exec_plan(make_coord_plan(("svc-a",), tx_id="t2"))
    assert p1.plan_hash() != p2.plan_hash()


def test_semantic_key_time_invariant():
    base = make_coord_plan(("svc-a", "svc-b"), tx_id="tx")
    plan = make_exec_plan(base)
    k1 = semantic_execution_key(plan)
    assert k1 == semantic_execution_key(plan)
    # different tx -> different key
    other = make_exec_plan(make_coord_plan(("svc-a", "svc-b"), tx_id="tx2"))
    assert semantic_execution_key(other) != k1


def test_receipt_hash_stable_and_canonical_ordering():
    r1 = ExecutionReceipt(
        execution_id="e1", global_tx_id="g", generation=1, plan_hash="ph",
        service_set_hash=service_set_hash(("a", "b")), started_at_monotonic=1.0,
        completed_at_monotonic=2.0, mode="rehearsal",
        child_outcomes=(("b", "CHILD_VERIFIED"), ("a", "CHILD_VERIFIED")),
        verification_summary="ok", stabilization_summary="ok",
        compensation_required=False, final_disposition="SIMULATED_COMMITTED",
        adapter_call_count=2,
    )
    # child_outcomes order is canonicalized inside the receipt hash, so two
    # orders of the same outcome set hash identically and stable.
    r2 = ExecutionReceipt(
        execution_id="e1", global_tx_id="g", generation=1, plan_hash="ph",
        service_set_hash=service_set_hash(("a", "b")), started_at_monotonic=1.0,
        completed_at_monotonic=2.0, mode="rehearsal",
        child_outcomes=(("a", "CHILD_VERIFIED"), ("b", "CHILD_VERIFIED")),
        verification_summary="ok", stabilization_summary="ok",
        compensation_required=False, final_disposition="SIMULATED_COMMITTED",
        adapter_call_count=2,
    )
    assert r1.receipt_hash() == r1.receipt_hash()
    assert r1.receipt_hash() == r2.receipt_hash()
    # a materially different disposition changes the hash
    r3 = ExecutionReceipt(
        execution_id="e1", global_tx_id="g", generation=1, plan_hash="ph",
        service_set_hash=service_set_hash(("a", "b")), started_at_monotonic=1.0,
        completed_at_monotonic=2.0, mode="rehearsal",
        child_outcomes=(("a", "CHILD_VERIFIED"), ("b", "CHILD_VERIFIED")),
        verification_summary="ok", stabilization_summary="failed",
        compensation_required=False, final_disposition="MANUAL_REVIEW_REQUIRED",
        adapter_call_count=2,
    )
    assert r1.receipt_hash() != r3.receipt_hash()
    assert service_set_hash(("a", "b")) == service_set_hash(("a", "b"))


def test_child_outcome_never_committed_directly():
    # adapter SUCCEEDED maps only to SIMULATED_SUCCEEDED, never CHILD_TERMINAL
    from agent.multi_service_execution.fake_adapter import FakeAdapterResult
    from agent.multi_service_execution.outcome import adapter_outcome_to_child_state
    res = FakeAdapterResult(outcome=AdapterOutcome.ADAPTER_SUCCEEDED, effect="e")
    state = adapter_outcome_to_child_state(res)
    assert state == ChildExecutionState.CHILD_SIMULATED_SUCCEEDED
    assert state != ChildExecutionState.CHILD_TERMINAL