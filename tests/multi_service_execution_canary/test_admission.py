import dataclasses

import pytest

from agent.multi_service_execution_canary import CanaryDecision, MultiServiceCanaryAdmission


def evaluate(admission, request, green_gates, **changes):
    gates = dict(green_gates)
    gates.update(changes)
    return admission.evaluate(request, now=100.0, **gates)


def test_exact_current_request_is_admitted_only_for_simulation(exact_registry, exact_request, green_gates):
    result = evaluate(MultiServiceCanaryAdmission(exact_registry), exact_request(), green_gates)
    assert result.decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED
    assert result.allowed is True
    assert result.reason == "admitted-for-simulation"


@pytest.mark.parametrize(("change", "decision", "reason"), [
    ({"baseline_sha": "old"}, CanaryDecision.REVALIDATE_REQUIRED, "baseline-drift"),
    ({"registry_digest": "old"}, CanaryDecision.REVALIDATE_REQUIRED, "registry-drift"),
    ({"graph_digest": "old"}, CanaryDecision.REVALIDATE_REQUIRED, "graph-drift"),
    ({"expires_monotonic": 99.0}, CanaryDecision.REVALIDATE_REQUIRED, "expired"),
    ({"operation": "RESTART"}, CanaryDecision.DENIED, "capability-binding"),
    ({"risk": "LOW"}, CanaryDecision.DENIED, "capability-binding"),
    ({"blast": "SERVICE"}, CanaryDecision.DENIED, "capability-binding"),
])
def test_request_binding_is_fail_closed(exact_registry, exact_request, green_gates, change, decision, reason):
    result = evaluate(MultiServiceCanaryAdmission(exact_registry), exact_request(**change), green_gates)
    assert result.decision is decision
    assert result.reason == reason
    assert result.allowed is False


@pytest.mark.parametrize("gate", ["identity_valid", "graph_healthy", "approval_valid", "budget_available", "locks_available", "kill_switch_off", "system_control_off", "generic_service_control_denied", "real_adapter_disabled"])
def test_every_admission_gate_is_required(exact_registry, exact_request, green_gates, gate):
    result = evaluate(MultiServiceCanaryAdmission(exact_registry), exact_request(), green_gates, **{gate: False})
    assert result.allowed is False
    assert result.decision in {CanaryDecision.DENIED, CanaryDecision.REVALIDATE_REQUIRED, CanaryDecision.CANARY_DISABLED}
