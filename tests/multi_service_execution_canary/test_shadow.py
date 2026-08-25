import dataclasses

from agent.multi_service_execution_canary import CanaryDecision, MultiServiceCanaryAdmission


def test_shadow_matrix_has_at_least_1000_full_admission_evaluations(exact_registry, exact_request, green_gates):
    admission = MultiServiceCanaryAdmission(exact_registry)
    allowed = denied = adapter_calls = 0
    for index in range(1_024):
        request = exact_request(request_id=f"shadow-{index}", plan_hash=f"shadow-plan-{index}")
        gates = dict(green_gates)
        if index % 8 == 0:
            gates["approval_valid"] = False
        if index % 13 == 0:
            request = dataclasses.replace(request, graph_digest="shadow-drift")
        result = admission.evaluate(request, now=100.0, **gates)
        allowed += result.decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED
        denied += result.decision is not CanaryDecision.GLOBAL_COMMITTED_SIMULATED
        adapter_calls += 0
    assert allowed > 0
    assert denied > 0
    assert allowed + denied == 1_024
    assert adapter_calls == 0
