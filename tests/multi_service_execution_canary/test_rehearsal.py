from agent.multi_service_execution_canary import CanaryDecision, build_canary_pipeline


def test_rehearsal_runs_at_least_1000_isolated_simulation_scenarios(tmp_path, exact_request, green_gates, fixed_clock):
    counts = {decision: 0 for decision in CanaryDecision}
    real_effects = 0
    for index in range(1_000):
        pipeline = build_canary_pipeline(tmp_path / str(index), clock=fixed_clock)
        selector = index % 4
        scenario = {}
        options = {}
        if selector == 1:
            scenario = {"canary-service-a": "SIMULATED_FAILURE"}
        elif selector == 2:
            scenario = {"canary-service-b": "SIMULATED_UNKNOWN"}
        elif selector == 3:
            options = {"health_ok": False}
        result = pipeline.evaluate(
            exact_request(request_id=f"rehearsal-{index}", plan_hash=f"plan-{index}"),
            scenario=scenario,
            **green_gates,
            **options,
        )
        counts[result.decision] += 1
        real_effects += pipeline.telemetry.real_child_adapter_calls
        real_effects += pipeline.telemetry.real_compensation_adapter_calls
        assert result.real_global_commit is False
    assert counts[CanaryDecision.GLOBAL_COMMITTED_SIMULATED] == 250
    assert counts[CanaryDecision.COMPENSATION_REQUIRED_SIMULATED] == 500
    assert counts[CanaryDecision.UNKNOWN_OUTCOME] == 250
    assert real_effects == 0
