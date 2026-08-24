"""Sprint 1.3.17 — approval binding + gates (§17)."""

from __future__ import annotations

from agent.multi_service_execution import approval_binding_valid, approval_ttl_valid
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan, make_pipeline,
)


def _approvals(plan):
    return {sid: f"ap-{sid}" for sid in plan.service_set}


def test_valid_global_plus_child_approvals():
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    binding = {"svc-a": "ap-svc-a", "svc-b": "ap-svc-b"}
    ok, _ = approval_binding_valid(plan, global_approval_id="g-ap",
                                   child_approvals=_approvals(plan),
                                   approval_binding=binding)
    assert ok is True


def test_missing_global_approval_invalid():
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    ok, reason = approval_binding_valid(plan, global_approval_id="",
                                        child_approvals=_approvals(plan))
    assert ok is False and "global" in reason


def test_missing_child_approval_invalid():
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    partial = {"svc-a": "ap-svc-a"}  # svc-b missing
    ok, reason = approval_binding_valid(plan, global_approval_id="g-ap",
                                        child_approvals=partial)
    assert ok is False and "svc-b" in reason


def test_child_approval_drift_invalid():
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    ok, reason = approval_binding_valid(plan, global_approval_id="g-ap",
                                        child_approvals={"svc-a": "ap-wrong"},
                                        approval_binding={"svc-a": "ap-svc-a"})
    assert ok is False and "drift" in reason


def test_approval_ttl_expiry_fail_closed():
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    assert approval_ttl_valid(plan, approval_ttl_until=100.0, now_monotonic=50.0) is True
    assert approval_ttl_valid(plan, approval_ttl_until=50.0, now_monotonic=100.0) is False


def test_invalid_approval_blocks_pipeline(tmp_path):
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    r = pipeline.execute(plan, child_admissions=green_admissions(plan),
                         approvals_valid=False)
    assert r["adapter_call_count"] == 0
    assert r["global_state"] == "EXECUTION_DENIED"