from agent.multi_service_execution_canary import CanaryDecision, build_canary_pipeline


def test_success_telemetry_distinguishes_simulation_from_real_effects(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    result = pipeline.evaluate(exact_request(), **green_gates)
    telemetry = pipeline.telemetry
    assert result.decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED
    assert (telemetry.canary_requests, telemetry.canary_allowed, telemetry.canary_simulated) == (1, 1, 1)
    assert telemetry.simulated_child_calls == 2
    assert telemetry.real_child_adapter_calls == 0
    assert telemetry.real_compensation_adapter_calls == 0


def test_unknown_and_replay_counters_are_scalar_and_non_authoritative(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    pipeline.evaluate(exact_request(), scenario={"canary-service-a": "invalid-value"}, **green_gates)
    pipeline.evaluate(exact_request(), **green_gates)
    telemetry = pipeline.telemetry
    assert telemetry.canary_requests == 2
    assert telemetry.canary_unknown == 1
    assert telemetry.canary_recovery_required == 1
    assert telemetry.canary_duplicates == 1
    assert telemetry.real_child_adapter_calls == telemetry.real_compensation_adapter_calls == 0


def test_pre_adapter_denial_increments_denied_without_simulated(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    result = pipeline.evaluate(exact_request(), **(green_gates | {"approval_valid": False}))
    assert result.decision is CanaryDecision.DENIED
    assert pipeline.telemetry.canary_denied == 1
    assert pipeline.telemetry.canary_simulated == 0
    assert pipeline.telemetry.simulated_child_calls == 0
