"""ApprovalManager tests (Sprint 1.0.2)."""

from datetime import datetime, timedelta, timezone

import pytest

from agent.execution.approval import ApprovalManager, ApprovalStatus
from agent.execution.exceptions import ApprovalAlreadyDecided, ApprovalExpired


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def _manager(ttl=None, clock=None):
    return ApprovalManager(clock=clock or _Clock(), ttl_seconds=ttl)


def test_request_creates_pending():
    mgr = _manager()
    req = mgr.request("run-1", "step-2", reason="send to client")
    assert req.status is ApprovalStatus.PENDING
    assert req.run_id == "run-1"
    assert req.step_id == "step-2"
    assert req.reason == "send to client"
    assert req.created_at is not None


def test_request_sequential_ids():
    mgr = _manager()
    assert mgr.request("r", "s").id == "approval-r-1"
    assert mgr.request("r", "s").id == "approval-r-2"


def test_approval_ids_globally_unique_per_run():
    """Sprint 1.0.6.2 — approval ids carry the run prefix so two runs
    creating an approval never collide on the PK(id) table."""
    mgr = _manager()
    a1 = mgr.request("run-A", "s")
    a2 = mgr.request("run-B", "s")
    assert a1.id.startswith("approval-run-A-")
    assert a2.id.startswith("approval-run-B-")
    assert a1.id != a2.id
    assert mgr.request("run-A", "s").id.startswith("approval-run-A-3")  # seq within run


def test_ttl_sets_expires_at():
    clock = _Clock()
    mgr = _manager(ttl=3600, clock=clock)
    req = mgr.request("r", "s")
    assert req.expires_at == clock.now + timedelta(seconds=3600)


def test_no_ttl_no_expiry():
    req = _manager().request("r", "s")
    assert req.expires_at is None


def test_approve():
    mgr = _manager()
    req = mgr.request("r", "s")
    assert mgr.approve(req.id).status is ApprovalStatus.APPROVED
    assert req.status is ApprovalStatus.APPROVED


def test_reject():
    mgr = _manager()
    req = mgr.request("r", "s")
    assert mgr.reject(req.id).status is ApprovalStatus.REJECTED


def test_expire_explicit():
    mgr = _manager()
    req = mgr.request("r", "s")
    assert mgr.expire(req.id).status is ApprovalStatus.EXPIRED


def test_duplicate_approve_raises():
    mgr = _manager()
    req = mgr.request("r", "s")
    mgr.approve(req.id)
    with pytest.raises(ApprovalAlreadyDecided):
        mgr.approve(req.id)
    with pytest.raises(ApprovalAlreadyDecided):
        mgr.reject(req.id)


def test_duplicate_reject_raises():
    mgr = _manager()
    req = mgr.request("r", "s")
    mgr.reject(req.id)
    with pytest.raises(ApprovalAlreadyDecided):
        mgr.reject(req.id)


def test_decide_expired_raises_and_marks_expired():
    clock = _Clock()
    mgr = _manager(ttl=10, clock=clock)
    req = mgr.request("r", "s")
    clock.advance(11)
    with pytest.raises(ApprovalExpired):
        mgr.approve(req.id)
    assert req.status is ApprovalStatus.EXPIRED


def test_is_overdue():
    clock = _Clock()
    mgr = _manager(ttl=10, clock=clock)
    req = mgr.request("r", "s")
    assert mgr.is_overdue(req) is False
    clock.advance(11)
    assert mgr.is_overdue(req) is True


def test_expire_overdue_sweep():
    clock = _Clock()
    mgr = _manager(ttl=10, clock=clock)
    stale = mgr.request("r", "s1")
    clock.advance(11)
    fresh = mgr.request("r", "s2")  # created after the window → not overdue
    expired = mgr.expire_overdue()
    assert [r.id for r in expired] == [stale.id]
    assert stale.status is ApprovalStatus.EXPIRED
    assert fresh.status is ApprovalStatus.PENDING


def test_list_pending():
    mgr = _manager()
    a = mgr.request("r", "s1")
    b = mgr.request("r", "s2")
    mgr.approve(a.id)
    assert [r.id for r in mgr.list_pending()] == [b.id]


def test_get_unknown_raises():
    mgr = _manager()
    with pytest.raises(KeyError):
        mgr.get("approval-99")


def test_is_decided_property():
    mgr = _manager()
    req = mgr.request("r", "s")
    assert req.is_decided is False
    mgr.approve(req.id)
    assert req.is_decided is True


def test_request_serialization():
    mgr = _manager(ttl=60)
    req = mgr.request("r", "s", reason="why")
    data = req.to_dict()
    assert data["id"] == req.id
    assert data["status"] == "pending"
    assert data["step_id"] == "s"
    assert data["expires_at"] is not None
