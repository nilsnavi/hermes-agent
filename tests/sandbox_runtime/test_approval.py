"""Approval — run-scoped, plan-scoped, version-guarded, TTL, single-use (Sprint 1.3.5 §10)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.sandbox_runtime.conftest import make_request, utcnow
from agent.sandbox_runtime.approval import ApprovalManager, ApprovalStatus
from agent.sandbox_runtime.exceptions import (
    ApprovalExpired,
    ApprovalInvalid,
    ApprovalReuse,
)
from agent.sandbox_runtime.models import SandboxMutationPlan


def _plan(req, plan_id="plan-1", fingerprint="fp"):
    return SandboxMutationPlan(
        plan_id=plan_id,
        request_id=req.request_id,
        resolved_target="/sandbox/x",
        operation=req.operation,
        resource_type=req.resource_type,
        before_state="absent",
        expected_after_state="present",
        risk=req.risk_class,
        approval_required=True,
        backup_required=True,
        verification_strategy="hash",
        rollback_strategy="snapshot",
        health_strategy="sandbox",
        preflight_fingerprint=fingerprint,
        created_at=utcnow(),
        expires_at=None,
    )


def test_approval_issue_and_validate(clock, make_req):
    mgr = ApprovalManager(clock=clock)
    req = make_req(run_id="run-A")
    plan = _plan(req)
    aid = mgr.issue(plan, requested_by="operator", ttl_s=300)
    verdict = mgr.validate(aid, plan, run_id="run-A")
    assert verdict.ok
    assert verdict.approval_id == aid


def test_approval_single_use(clock, make_req):
    mgr = ApprovalManager(clock=clock)
    req = make_req(run_id="run-B")
    plan = _plan(req)
    aid = mgr.issue(plan, requested_by="op", ttl_s=300)
    assert mgr.validate(aid, plan, run_id="run-B").ok
    # second use of the same approval → refused
    with pytest.raises(ApprovalReuse):
        mgr.validate(aid, plan, run_id="run-B")


def test_approval_cannot_be_used_for_other_plan(clock, make_req):
    mgr = ApprovalManager(clock=clock)
    req = make_req(run_id="run-C")
    plan1 = _plan(req, plan_id="plan-1")
    plan2 = _plan(req, plan_id="plan-2")
    aid = mgr.issue(plan1, requested_by="op", ttl_s=300)
    with pytest.raises(ApprovalInvalid):
        mgr.validate(aid, plan2, run_id="run-C")


def test_approval_cannot_be_used_for_other_run(clock, make_req):
    mgr = ApprovalManager(clock=clock)
    req = make_req(run_id="run-D")
    plan = _plan(req)
    aid = mgr.issue(plan, requested_by="op", ttl_s=300)
    with pytest.raises(ApprovalInvalid):
        mgr.validate(aid, plan, run_id="run-OTHER")


def test_approval_expires(clock, make_req):
    mgr = ApprovalManager(clock=clock)
    req = make_req(run_id="run-E")
    plan = _plan(req)
    aid = mgr.issue(plan, requested_by="op", ttl_s=1)

    # advance the SAME manager's clock past the TTL
    class _Later:
        def __init__(self, base):
            self._base = base

        def __call__(self):
            return self._base + timedelta(seconds=120)

    mgr._clock = _Later(clock())
    with pytest.raises(ApprovalExpired):
        mgr.validate(aid, plan, run_id="run-E")


def test_approval_unknown_id(clock, make_req):
    mgr = ApprovalManager(clock=clock)
    req = make_req(run_id="run-F")
    plan = _plan(req)
    with pytest.raises(ApprovalInvalid):
        mgr.validate("no-such-approval", plan, run_id="run-F")


def test_double_approve_no_second_right(clock, make_req):
    mgr = ApprovalManager(clock=clock)
    req = make_req(run_id="run-G")
    plan = _plan(req)
    mgr.issue(plan, requested_by="op", ttl_s=300)
    # issuing again for the same plan must not create a second usable right
    with pytest.raises(ApprovalReuse):
        mgr.issue(plan, requested_by="op", ttl_s=300)


def test_approval_status_tracked(clock, make_req):
    mgr = ApprovalManager(clock=clock)
    req = make_req(run_id="run-H")
    plan = _plan(req)
    aid = mgr.issue(plan, requested_by="op", ttl_s=300)
    assert mgr.status(aid) == ApprovalStatus.PENDING
    mgr.validate(aid, plan, run_id="run-H")
    assert mgr.status(aid) == ApprovalStatus.USED
