"""Sprint 1.3.16 tests — lock recovery, budget recovery, approval recovery."""
from __future__ import annotations

from agent.multi_service_recovery.lock_recovery import (
    LockRecoveryState, can_takeover, classify_lock_owner,
)
from agent.multi_service_recovery.budget_recovery import (
    BudgetState, classify_budget_state, consume_allowed, refund_allowed,
)
from agent.multi_service_recovery.approval_recovery import (
    ApprovalRecoveryState, approval_valid, classify_approval,
)


def test_live_owner_no_takeover():
    got = classify_lock_owner(
        lock_record={"pid": 1, "start": "p1", "created": 10.0, "expiry": 8000.0},
        now_monotonic=5000.0, same_process_now=True)
    assert got == LockRecoveryState.LIVE_OWNER
    assert can_takeover(got) is False


def test_pid_reuse_denied():
    got = classify_lock_owner(
        lock_record={"pid": 1234, "start": "pid:1234-start:999", "created": 10.0,
                     "expiry": 8000.0},
        now_monotonic=5000.0, same_process_now=False)
    assert got == LockRecoveryState.PID_REUSE
    assert can_takeover(got) is False


def test_stale_dead_owner_takeover_only_validated():
    got = classify_lock_owner(
        lock_record={"pid": 9, "start": "p9", "created": 10.0, "expiry": 100.0},
        now_monotonic=5000.0, same_process_now=None)
    assert got == LockRecoveryState.STALE_DEAD
    assert can_takeover(got) is True


def test_active_execution_no_steal():
    got = classify_lock_owner(lock_record={}, now_monotonic=0.0,
                              active_execution=True)
    assert got == LockRecoveryState.ACTIVE_EXECUTION
    assert can_takeover(got) is False


def test_budget_never_refunded_after_unknown():
    state = classify_budget_state(reserved=False, consumed=True,
                                  released=False, executed_evidence=False)
    assert state == BudgetState.UNKNOWN
    assert refund_allowed(state) is False


def test_budget_release_only_durable_no_execution_proof():
    state = classify_budget_state(reserved=True, consumed=False,
                                  released=False, executed_evidence=False)
    assert state == BudgetState.RESERVED
    assert refund_allowed(state) is True


def test_budget_no_double_consume():
    consumed = classify_budget_state(reserved=False, consumed=True,
                                     released=False, executed_evidence=True)
    assert consumed == BudgetState.CONSUMED
    assert consume_allowed(consumed) is False


def test_approval_recovery_single_use():
    assert classify_approval(consumed=True) == ApprovalRecoveryState.CONSUMED
    assert classify_approval(expired=True) == ApprovalRecoveryState.EXPIRED
    assert classify_approval(mismatch=True) == ApprovalRecoveryState.MISMATCH
    v = classify_approval(consumed=False, expired=False, mismatch=False)
    assert v == ApprovalRecoveryState.VALID_FOR_RECOVERY_VERIFY
    assert approval_valid(v) is True
    assert approval_valid(ApprovalRecoveryState.CONSUMED) is False