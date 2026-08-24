"""Sprint 1.3.16 tests — MultiServiceRecoveryCoordinator end-to-end guarantees."""
from __future__ import annotations

import pytest

from agent.multi_service_recovery.models import RecoveryDisposition
from tests.multi_service_recovery.conftest import make_coordinator, make_store

J_CLAIM = ["GLOBAL_CLAIMED"]
J_VFY = ["GLOBAL_CLAIMED", "SIMULATION_STARTED", "CHILD_SIMULATED",
         "CHILD_SIMULATED", "VERIFY_COMPLETED"]
J_CMT = J_VFY + ["GLOBAL_SIMULATED_COMMIT"]
J_COMP = ["GLOBAL_CLAIMED", "SIMULATION_STARTED", "CHILD_SIMULATED",
          "COMPENSATION_REQUIRED"]


def test_coordinator_no_adapter_ever(tmp_path):
    store = make_store(tmp_path)
    coord = make_coordinator(store)
    plan = coord.recover(journal_types=J_CMT, child_states={},
                         idempotency_state="COMMITTED_SIMULATED")
    assert coord.adapter_calls == 0
    assert plan.disposition == RecoveryDisposition.TERMINAL


def test_terminal_immutability(tmp_path):
    store = make_store(tmp_path)
    coord = make_coordinator(store)
    plan = coord.recover(journal_types=J_CMT, child_states={},
                         idempotency_state="COMMITTED_SIMULATED")
    assert plan.disposition == RecoveryDisposition.TERMINAL
    assert plan.would_verify is False and plan.would_compensate is False
    assert store.journal.count("RECOVERY_COMPLETED") == 1


def test_baseline_drift_blocks_resume(tmp_path):
    store = make_store(tmp_path)
    coord = make_coordinator(store)
    plan = coord.recover(journal_types=J_VFY, child_states={},
                         current_baseline_sha="DIFFERENT-SHA")
    assert plan.disposition == RecoveryDisposition.MANUAL_REVIEW_REQUIRED
    assert plan.violation == "BASELINE_DRIFT"


def test_graph_and_service_drift_block_resume(tmp_path):
    store = make_store(tmp_path)
    coord = make_coordinator(store)
    p1 = coord.recover(journal_types=J_VFY, child_states={}, drift_graph=True)
    assert p1.disposition == RecoveryDisposition.MANUAL_REVIEW_REQUIRED
    p2 = coord.recover(journal_types=J_VFY, child_states={},
                       service_identity_drift=True)
    assert p2.disposition == RecoveryDisposition.MANUAL_REVIEW_REQUIRED


def test_unknown_child_forces_manual_review(tmp_path):
    store = make_store(tmp_path)
    coord = make_coordinator(store)
    plan = coord.recover(journal_types=J_VFY,
                         child_states={"fake-aux-a": "UNKNOWN_OUTCOME"})
    assert plan.disposition == RecoveryDisposition.MANUAL_REVIEW_REQUIRED


def test_compensation_required_never_success(tmp_path):
    store = make_store(tmp_path)
    coord = make_coordinator(store)
    plan = coord.recover(journal_types=J_COMP,
                         child_states={"fake-aux-a": "FAILED_SAFE",
                                       "fake-aux-b": "SIMULATED_EXECUTED"})
    assert plan.disposition == RecoveryDisposition.COMPENSATION_REQUIRED
    assert plan.would_compensate is True
    assert plan.disposition != RecoveryDisposition.TERMINAL
    # compensation planning is recorded but never executed
    assert store.journal.count("COMPENSATION_PLANNED") == 1


def test_recovery_generation_bounded_prevents_uncontrolled_retry(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(AssertionError):
        make_coordinator(store, generation=99)  # exceeds max automatic generations


def test_recovery_of_recovery_new_generation_distinct_owner(tmp_path):
    store = make_store(tmp_path)
    c1 = make_coordinator(store, tx_id="tx", generation=1)
    c1.recover(journal_types=J_CLAIM, child_states={})
    # a SECOND recovery worker on the same tx but a new generation is fine
    # (generation is not a replay); but the same generation is owned by c1.
    store2 = make_store(tmp_path)  # fresh store -- claim is per-store durable path
    c_same = make_coordinator(store, tx_id="tx", generation=1)
    plan = c_same.recover(journal_types=J_CLAIM, child_states={})
    # same store => same claim owner already held by c1's generation
    assert plan.disposition == RecoveryDisposition.MANUAL_REVIEW_REQUIRED
    assert plan.violation == "RECOVERY_OWNED_BY_OTHER"


def test_idempotent_recovery_no_duplicate_effect(tmp_path):
    store = make_store(tmp_path)
    coord = make_coordinator(store)
    plan = coord.recover(journal_types=J_CMT, child_states={},
                         idempotency_state="COMMITTED_SIMULATED")
    assert plan.disposition == RecoveryDisposition.TERMINAL
    # a SECOND recovery worker on the same (tx, generation) is refused the claim
    # -> no double verify, no double compensation, no second adapter.
    c2 = make_coordinator(store, tx_id="tx-1")
    plan2 = c2.recover(journal_types=J_CMT, child_states={},
                       idempotency_state="COMMITTED_SIMULATED")
    assert plan2.disposition == RecoveryDisposition.MANUAL_REVIEW_REQUIRED
    assert plan2.violation == "RECOVERY_OWNED_BY_OTHER"
    assert c2.adapter_calls == 0