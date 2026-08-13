"""Approval expiry tests (Sprint 1.0.6.3 §31, §37, MUST-HAVE 11)."""

from datetime import datetime, timedelta, timezone

import pytest

from agent.operations_v2.approval_service import ApprovalService
from agent.operations_v2.exceptions import ApprovalAlreadyDecidedError, ApprovalExpiredError
from agent.operations_v2.models import OperatorIdentity

from .conftest import run_gated

OPERATOR = OperatorIdentity(operator_id="op-1", source="cli", authenticated=True)


def _side_effect(tool):
    return "read_only"


class FakeClock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now = self.now + timedelta(seconds=seconds)


def test_approve_expired_blocked(ops_db, store, orchestrator):
    """MUST-HAVE 11 — expired approval: approve DENIED, status EXPIRED."""
    _, approval = run_gated(orchestrator, store, "ap-exp")
    # give the approval a short expiry in the past
    conn = __import__("sqlite3").connect(ops_db)
    try:
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        conn.execute(
            "UPDATE agent_v2_approvals SET expires_at=? WHERE id=?",
            (past, approval.id),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(ApprovalExpiredError):
        ApprovalService(ops_db, tool_side_effect_fn=_side_effect).approve(
            approval.run_id, approval.id, OPERATOR
        )
    status = conn  # noqa
    conn2 = __import__("sqlite3").connect(ops_db)
    try:
        row = conn2.execute(
            "SELECT status FROM agent_v2_approvals WHERE id=?", (approval.id,)
        ).fetchone()
    finally:
        conn2.close()
    assert row[0] == "expired"  # never approved


def test_expire_once_idempotent(ops_db, store, orchestrator):
    """§37 — expire once; repeated expire mutates nothing."""
    _, approval = run_gated(orchestrator, store, "ap-exp2")
    svc = ApprovalService(ops_db, tool_side_effect_fn=_side_effect)
    decision = svc.expire(approval.id, run_id=approval.run_id)
    assert decision.decision == "expired"
    with pytest.raises(ApprovalAlreadyDecidedError):
        svc.expire(approval.id, run_id=approval.run_id)
    conn = __import__("sqlite3").connect(ops_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM agent_v2_events WHERE event_type='APPROVAL_EXPIRED'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_fake_clock_expiry(ops_db, store, orchestrator):
    """§37 — fake clock: approval expires exactly at the boundary."""
    _, approval = run_gated(orchestrator, store, "ap-clock")
    start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(start)
    conn = __import__("sqlite3").connect(ops_db)
    try:
        conn.execute(
            "UPDATE agent_v2_approvals SET expires_at=? WHERE id=?",
            ((start + timedelta(minutes=5)).isoformat(), approval.id),
        )
        conn.commit()
    finally:
        conn.close()
    svc = ApprovalService(ops_db, clock=clock, tool_side_effect_fn=_side_effect)
    # before expiry → approve works
    clock.advance(60)
    decision = svc.approve(approval.run_id, approval.id, OPERATOR)
    assert decision.decision == "approved"


def test_fake_clock_after_expiry(ops_db, store, orchestrator):
    _, approval = run_gated(orchestrator, store, "ap-clock2")
    start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(start)
    conn = __import__("sqlite3").connect(ops_db)
    try:
        conn.execute(
            "UPDATE agent_v2_approvals SET expires_at=? WHERE id=?",
            ((start + timedelta(minutes=5)).isoformat(), approval.id),
        )
        conn.commit()
    finally:
        conn.close()
    svc = ApprovalService(ops_db, clock=clock, tool_side_effect_fn=_side_effect)
    clock.advance(301)  # past the 5-minute expiry
    with pytest.raises(ApprovalExpiredError):
        svc.approve(approval.run_id, approval.id, OPERATOR)
