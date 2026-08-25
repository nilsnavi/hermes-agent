import json

import pytest

from agent.multi_service_execution_canary import (
    CanaryBudgetLimits,
    CanaryDecision,
    CanarySimulationBudget,
    approval_binding,
    approval_valid,
    build_canary_pipeline,
    canonical_lock_order,
    lock_all_or_none,
    renewal_allowed,
)


@pytest.mark.parametrize("gate", ["locks_available", "budget_available", "approval_valid"])
def test_lock_budget_and_approval_deny_before_any_child(tmp_path, exact_request, green_gates, fixed_clock, gate):
    pipeline = build_canary_pipeline(tmp_path / gate, clock=fixed_clock)
    gates = green_gates | {gate: False}
    result = pipeline.evaluate(exact_request(plan_hash=gate), **gates)
    assert result.decision is CanaryDecision.DENIED
    assert result.adapter_call_count == 0
    assert pipeline.telemetry.simulated_child_calls == 0


def test_terminal_receipt_consumes_one_attempt_one_success_one_approval(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    pipeline.evaluate(exact_request(), **green_gates)
    state = json.loads((tmp_path / "canary-store.json").read_text())
    assert state["budget_attempts"] == 1
    assert state["budget_success"] == 1
    assert state["approvals"] == ["approval-1"]
    assert state["kill_switch"] is True


def test_kill_switch_persists_across_pipeline_instances(tmp_path, exact_request, green_gates, fixed_clock):
    first = build_canary_pipeline(tmp_path, clock=fixed_clock)
    first.evaluate(exact_request(plan_hash="first"), **green_gates)
    second = build_canary_pipeline(tmp_path, clock=fixed_clock)
    denied = second.evaluate(exact_request(plan_hash="second"), **green_gates)
    assert denied.decision is CanaryDecision.CANARY_DISABLED
    assert denied.adapter_call_count == 0
    assert second.telemetry.kill_switch_denials == 1


def test_approval_binding_covers_full_semantic_plan(exact_request):
    request = exact_request()
    binding = approval_binding(request)
    assert approval_valid(request, binding, now=100.0) is True
    assert approval_valid(exact_request(plan_hash="other"), binding, now=100.0) is False
    assert approval_valid(request, binding, now=1_001.0) is False


def test_simulation_budget_enforces_attempt_and_success_caps():
    by_attempt = CanarySimulationBudget(CanaryBudgetLimits(max_attempts_per_hour=2, max_simulated_success_per_hour=2))
    assert by_attempt.consume(success=False) is True
    assert by_attempt.consume(success=False) is True
    assert by_attempt.consume(success=False) is False
    by_success = CanarySimulationBudget(CanaryBudgetLimits(max_attempts_per_hour=5, max_simulated_success_per_hour=1))
    assert by_success.consume(success=True) is True
    assert by_success.consume(success=True) is False


def test_lock_set_is_canonical_all_or_none_and_owner_bound():
    reverse = ("canary-service-b", "canary-service-a")
    assert canonical_lock_order(reverse) == ("canary-service-a", "canary-service-b")
    assert lock_all_or_none(reverse, {"canary-service-a": True, "canary-service-b": True}) == canonical_lock_order(reverse)
    assert lock_all_or_none(reverse, {"canary-service-a": True, "canary-service-b": False}) == ()
    assert renewal_allowed(owner="runtime-1", requester="runtime-1", live_owner=True) is True
    assert renewal_allowed(owner="runtime-1", requester="runtime-2", live_owner=True) is False
    assert renewal_allowed(owner="runtime-1", requester="runtime-1", live_owner=False) is False
