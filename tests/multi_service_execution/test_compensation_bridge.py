"""Sprint 1.3.17 — compensation bridge (§20) + recovery bridge (§22)."""

from __future__ import annotations

from agent.multi_service_execution import build_compensation_bridge_result
from agent.multi_service_execution.compensation_bridge import CompensationBridgeResult
from agent.multi_service_execution.models import ChildExecutionState
from agent.multi_service_execution.recovery_bridge import (
    recovery_allows_execution, recovery_requires_manual,
)
from tests.multi_service_execution.conftest import make_coord_plan, make_exec_plan


def test_no_failure_no_compensation():
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    states = {s: ChildExecutionState.CHILD_VERIFIED for s in plan.service_set}
    r = build_compensation_bridge_result(plan, states)
    assert r.compensation_required is False
    assert r.plan is None
    assert r.real_compensation_adapter_calls == 0


def test_failure_sets_compensation_required_and_plan():
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    states = {"svc-a": ChildExecutionState.CHILD_VERIFIED,
              "svc-b": ChildExecutionState.CHILD_SIMULATED_FAILED}
    r = build_compensation_bridge_result(plan, states, fail_child="svc-b")
    assert r.compensation_required is True
    assert r.plan is not None
    assert "svc-b" in r.failed_children
    assert r.real_compensation_adapter_calls == 0


def test_compensation_reverse_topological():
    # dependents (svc-c) must be compensated before dependents-holders (svc-a)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b", "svc-c")))
    states = {
        "svc-a": ChildExecutionState.CHILD_VERIFIED,
        "svc-b": ChildExecutionState.CHILD_SIMULATED_FAILED,
        "svc-c": ChildExecutionState.CHILD_SIMULATED_SUCCEEDED,
    }
    r = build_compensation_bridge_result(plan, states, fail_child="svc-b")
    assert r.compensation_required is True
    steps = r.plan.steps
    order = [s.service_id for s in steps]
    assert order == list(reversed(plan.topological_order))
    # NOT_STARTED-equivalent / no-effect children are NOOP (never compensated)
    noop = [s for s in steps if s.operation == "NOOP"]
    assert noop  # a non-effect child is never a real compensation step


def test_recovery_blocked_dispositions():
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    for disp in ("UNKNOWN_RECOVERY_STATE", "MANUAL_REVIEW_REQUIRED", "TERMINAL_RECOVERY"):
        allowed, reason = recovery_allows_execution(plan, {"classification": disp})
        assert allowed is False
    assert recovery_requires_manual(plan, {"classification": "UNKNOWN_RECOVERY_STATE"}) is True


def test_recovery_missing_evidence_fail_closed():
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    allowed, reason = recovery_allows_execution(plan, {})
    assert allowed is False
    assert "evidence" in reason


def test_recovery_clean_allows():
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    allowed, reason = recovery_allows_execution(plan, {"classification": "RECOVERY_CLEAN"})
    assert allowed is True