import dataclasses

from agent.multi_service_execution_canary import CanaryDecision, ChildExecutionIntent, OPERATION, build_canary_pipeline


def test_success_simulates_two_ordered_children_without_real_commit(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    result = pipeline.evaluate(exact_request(), **green_gates)
    assert result.decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED
    assert result.adapter_call_count == 2
    assert result.child_outcomes == (("canary-service-a", "SIMULATED_SUCCESS"), ("canary-service-b", "SIMULATED_SUCCESS"))
    assert result.real_global_commit is False
    assert pipeline.telemetry.real_child_adapter_calls == 0


def test_failure_stops_after_failed_child_and_never_calls_real_adapter(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    result = pipeline.evaluate(exact_request(), scenario={"canary-service-a": "SIMULATED_FAILURE"}, **green_gates)
    assert result.decision is CanaryDecision.COMPENSATION_REQUIRED_SIMULATED
    assert result.adapter_call_count == 1
    assert result.child_outcomes == (("canary-service-a", "SIMULATED_FAILURE"),)
    assert pipeline.telemetry.real_child_adapter_calls == 0


def test_child_intent_has_typed_simulation_only_surface():
    fields = {field.name for field in dataclasses.fields(ChildExecutionIntent)}
    assert fields == {"service_id", "operation", "plan_hash", "expected_effect"}
    intent = ChildExecutionIntent("canary-service-a", OPERATION, "plan")
    assert intent.expected_effect == "SIMULATED_EFFECT_ONLY"
    assert not fields.intersection({"command", "argv", "shell", "unit", "path", "signal"})
