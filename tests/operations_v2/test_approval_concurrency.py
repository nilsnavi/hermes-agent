"""Approval concurrency tests (Sprint 1.0.6.3 §28-29, MUST-HAVE 8)."""

import sqlite3

import pytest

from agent.operations_v2.approval_service import ApprovalService
from agent.operations_v2.exceptions import ApprovalAlreadyDecidedError
from agent.operations_v2.models import OperatorIdentity

from .conftest import run_gated

OPERATOR = OperatorIdentity(operator_id="op-1", source="cli", authenticated=True)
OPERATOR_B = OperatorIdentity(operator_id="op-2", source="cli", authenticated=True)


def _side_effect(tool):
    return "read_only"


def _status(db_path, approval_id):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT status, decided_by FROM agent_v2_approvals WHERE id=?",
            (approval_id,),
        ).fetchone()
    finally:
        conn.close()


def test_double_approve_one_winner(ops_db, store, orchestrator):
    """MUST-HAVE 8 — two processes approve; exactly one succeeds."""
    _, approval = run_gated(orchestrator, store, "ap-race")
    svc_a = ApprovalService(ops_db, tool_side_effect_fn=_side_effect)
    svc_b = ApprovalService(ops_db, tool_side_effect_fn=_side_effect)

    first = svc_a.approve(approval.run_id, approval.id, OPERATOR)
    assert first.decision == "approved"
    with pytest.raises(ApprovalAlreadyDecidedError):
        svc_b.approve(approval.run_id, approval.id, OPERATOR_B)

    status = _status(ops_db, approval.id)
    assert status[0] == "approved"
    assert status[1] == "op-1"  # the winner's identity, single decision


def test_concurrent_threads_single_decision(ops_db, store, orchestrator):
    """§29 — two threads racing approve: exactly one writes the decision."""
    import threading

    _, approval = run_gated(orchestrator, store, "ap-threads")
    svc_a = ApprovalService(ops_db, tool_side_effect_fn=_side_effect)
    svc_b = ApprovalService(ops_db, tool_side_effect_fn=_side_effect)

    outcomes = []
    barrier = threading.Barrier(2)

    def worker(svc, operator):
        barrier.wait()
        try:
            svc.approve(approval.run_id, approval.id, operator)
            outcomes.append("ok")
        except ApprovalAlreadyDecidedError:
            outcomes.append("lost")
        except Exception as exc:  # concurrent update path
            outcomes.append(f"conflict:{type(exc).__name__}")

    threads = [
        threading.Thread(target=worker, args=(svc_a, OPERATOR)),
        threading.Thread(target=worker, args=(svc_b, OPERATOR_B)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert outcomes.count("ok") == 1, outcomes
    status = _status(ops_db, approval.id)
    assert status[0] == "approved"
    conn = sqlite3.connect(ops_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM agent_v2_events WHERE event_type='APPROVAL_APPROVED'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1  # one audit event, one decision


def test_approve_after_reject_blocked(ops_db, store, orchestrator):
    _, approval = run_gated(orchestrator, store, "ap-ar")
    svc = ApprovalService(ops_db, tool_side_effect_fn=_side_effect)
    svc.reject(approval.run_id, approval.id, OPERATOR)
    with pytest.raises(ApprovalAlreadyDecidedError):
        svc.approve(approval.run_id, approval.id, OPERATOR)
    with pytest.raises(ApprovalAlreadyDecidedError):
        svc.reject(approval.run_id, approval.id, OPERATOR)
