import pytest

from agent.multi_service_execution_canary import CanaryDecision, build_canary_pipeline


@pytest.mark.parametrize(("scenario", "decision", "calls", "compensation"), [
    ({"canary-service-a": "SIMULATED_FAILURE"}, CanaryDecision.COMPENSATION_REQUIRED_SIMULATED, 1, ("canary-service-b", "canary-service-a")),
    ({"canary-service-b": "SIMULATED_FAILURE"}, CanaryDecision.COMPENSATION_REQUIRED_SIMULATED, 2, ("canary-service-b", "canary-service-a")),
    ({"canary-service-a": "SIMULATED_UNKNOWN"}, CanaryDecision.UNKNOWN_OUTCOME, 1, ()),
    ({"canary-service-b": "SIMULATED_UNKNOWN"}, CanaryDecision.UNKNOWN_OUTCOME, 2, ()),
])
def test_failure_and_unknown_are_terminal_simulated_recovery_states(tmp_path, exact_request, green_gates, fixed_clock, scenario, decision, calls, compensation):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    result = pipeline.evaluate(exact_request(), scenario=scenario, **green_gates)
    replay = pipeline.evaluate(exact_request(), **green_gates)
    assert result.decision is decision
    assert result.adapter_call_count == calls
    assert result.compensation_order == compensation
    assert result.real_global_commit is False
    assert replay.replayed is True
    assert replay.decision is decision
    assert pipeline.telemetry.real_compensation_adapter_calls == 0


@pytest.mark.parametrize("post_gate", ["verify_ok", "health_ok", "stabilization_ok"])
def test_post_adapter_failure_requires_reverse_compensation_simulation(tmp_path, exact_request, green_gates, fixed_clock, post_gate):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    result = pipeline.evaluate(exact_request(), **green_gates, **{post_gate: False})
    assert result.decision is CanaryDecision.COMPENSATION_REQUIRED_SIMULATED
    assert result.adapter_call_count == 2
    assert result.compensation_order == ("canary-service-b", "canary-service-a")
    assert pipeline.telemetry.simulated_compensation_calls == 2
    assert pipeline.telemetry.real_compensation_adapter_calls == 0
