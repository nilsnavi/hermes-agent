import dataclasses

from agent.multi_service_execution_canary import CanaryDecision, build_canary_pipeline


def test_terminal_success_replays_by_semantic_intent_not_request_id(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    first = pipeline.evaluate(exact_request(request_id="first"), **green_gates)
    second = pipeline.evaluate(exact_request(request_id="retry"), **green_gates)
    assert first.decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED
    assert second.decision is first.decision
    assert second.replayed is True
    assert second.adapter_call_count == 0
    assert pipeline.telemetry.simulated_child_calls == 2


def test_semantic_key_binds_plan_generation_and_set(exact_request):
    base = exact_request()
    assert base.semantic_key() != dataclasses.replace(base, plan_hash="other").semantic_key()
    assert base.semantic_key() != dataclasses.replace(base, generation=2).semantic_key()
    assert base.semantic_key() == dataclasses.replace(base, request_id="other", approval_id="other").semantic_key()


def test_terminal_unknown_is_exactly_once(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    first = pipeline.evaluate(exact_request(), scenario={"canary-service-a": "SIMULATED_UNKNOWN"}, **green_gates)
    second = pipeline.evaluate(exact_request(), scenario={"canary-service-a": "SIMULATED_SUCCESS"}, **green_gates)
    assert first.decision is CanaryDecision.UNKNOWN_OUTCOME
    assert second.decision is CanaryDecision.UNKNOWN_OUTCOME
    assert second.replayed is True
    assert pipeline.telemetry.simulated_child_calls == 1
