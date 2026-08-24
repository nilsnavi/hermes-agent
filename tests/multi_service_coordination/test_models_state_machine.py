from __future__ import annotations

import pytest

from agent.multi_service_coordination.models import (
    CoordinatorState,
    check_transition,
    TERMINAL_STATES,
    MultiServiceChangePlan,
)


def test_happy_path_transitions_are_all_legal():
    edges = [
        (CoordinatorState.CREATED, CoordinatorState.PLANNED),
        (CoordinatorState.PLANNED, CoordinatorState.ELIGIBILITY_CHECKED),
        (CoordinatorState.ELIGIBILITY_CHECKED, CoordinatorState.LOCKS_ACQUIRED),
        (CoordinatorState.LOCKS_ACQUIRED, CoordinatorState.PREPARED),
        (CoordinatorState.PREPARED, CoordinatorState.BARRIER_READY),
        (CoordinatorState.BARRIER_READY, CoordinatorState.EXECUTION_READY),
        (CoordinatorState.EXECUTION_READY, CoordinatorState.SIMULATED_EXECUTING),
        (CoordinatorState.SIMULATED_EXECUTING, CoordinatorState.VERIFYING),
        (CoordinatorState.VERIFYING, CoordinatorState.COMMIT_READY),
        (CoordinatorState.COMMIT_READY, CoordinatorState.COMMITTED_SIMULATED),
    ]
    for old, new in edges:
        assert check_transition(old, new), f"{old}->{new}"


def test_no_real_executing_state_in_machine():
    # 1.3.15 model has no standalone EXECUTING; only SIMULATED_EXECUTING.
    assert "EXECUTING" not in {s.value for s in CoordinatorState}


def test_terminal_states_have_no_outgoing_edges():
    for term in TERMINAL_STATES:
        for other in CoordinatorState:
            if other == term:
                continue
            assert not check_transition(term, other), f"{term}->{other}"


def test_fail_corridor_reachable_from_non_terminal():
    # DENIED / compensation / unknown reachable from any non-terminal
    for s in (CoordinatorState.PLANNED, CoordinatorState.LOCKS_ACQUIRED,
              CoordinatorState.SIMULATED_EXECUTING, CoordinatorState.VERIFYING):
        assert check_transition(s, CoordinatorState.DENIED)
        assert check_transition(s, CoordinatorState.COMPENSATION_REQUIRED)
        assert check_transition(s, CoordinatorState.UNKNOWN_OUTCOME)
        assert check_transition(s, CoordinatorState.MANUAL_REVIEW_REQUIRED)


def test_illegal_skip_is_not_allowed():
    # CREATED cannot jump straight to SIMULATED_EXECUTING
    assert not check_transition(CoordinatorState.CREATED, CoordinatorState.SIMULATED_EXECUTING)


def test_no_live_executing_variant_denied():
    assert not check_transition(CoordinatorState.COMMIT_READY, CoordinatorState.EXECUTION_READY)


def test_plan_is_frozen():
    p = MultiServiceChangePlan(
        plan_id="p", transaction_id="t", baseline_sha="b", coordinator_version="v",
        created_at=0.0, expires_at=10.0, service_set=(), dependency_graph_digest="g",
        execution_order=(), rollback_order=(), operation_set=(), plan_hash="h",
    )
    with pytest.raises(Exception):
        setattr(p, "plan_id", "mutated")  # frozen dataclass rejects it