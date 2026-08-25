from concurrent.futures import ThreadPoolExecutor

from agent.multi_service_execution_canary import CanaryDecision, build_canary_pipeline


def test_fifty_coordinators_share_one_durable_terminal_result(tmp_path, exact_request, green_gates, fixed_clock):
    coordinators = [build_canary_pipeline(tmp_path, clock=fixed_clock) for _ in range(50)]
    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(lambda pipeline: pipeline.evaluate(exact_request(), **green_gates), coordinators))
    assert len(results) == 50
    assert sum(result.adapter_call_count > 0 for result in results) == 1
    assert sum(result.adapter_call_count == 0 for result in results) == 49
    assert {result.decision for result in results} <= {
        CanaryDecision.GLOBAL_COMMITTED_SIMULATED,
        CanaryDecision.DENIED,
    }


def test_one_hundred_claim_contenders_have_at_most_one_simulator(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    results = pipeline.race(exact_request(), contenders=100, **green_gates)
    assert len(results) == 100
    assert sum(result.adapter_call_count > 0 for result in results) == 1
    assert all(result.real_global_commit is False for result in results)


def test_one_hundred_duplicates_never_repeat_child_simulation(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    first = pipeline.evaluate(exact_request(), **green_gates)
    duplicates = [pipeline.evaluate(exact_request(request_id=f"duplicate-{i}"), **green_gates) for i in range(100)]
    assert first.adapter_call_count == 2
    assert len(duplicates) == 100
    assert all(result.replayed and result.adapter_call_count == 0 for result in duplicates)
    assert pipeline.telemetry.simulated_child_calls == 2


def test_one_hundred_reverse_order_requests_collapse_to_same_semantic_claim(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    first = pipeline.evaluate(exact_request(), **green_gates)
    reverse = [pipeline.evaluate(exact_request(request_id=f"reverse-{i}", service_ids=("canary-service-b", "canary-service-a")), **green_gates) for i in range(100)]
    assert first.decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED
    assert all(result.replayed for result in reverse)
    assert sum(result.adapter_call_count for result in reverse) == 0


def test_one_hundred_overlapping_unique_intents_end_with_persisted_kill_switch(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(tmp_path, clock=fixed_clock)
    requests = [exact_request(request_id=f"overlap-{i}", plan_hash=f"overlap-plan-{i}") for i in range(100)]
    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(lambda request: pipeline.evaluate(request, **green_gates), requests))
    assert len(results) == 100
    simulated = sum(result.decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED for result in results)
    assert simulated >= 1
    assert sum(result.adapter_call_count for result in results) == simulated * 2
    assert all(result.real_global_commit is False for result in results)
    after_race = pipeline.evaluate(
        exact_request(request_id="after-overlap", plan_hash="after-overlap"),
        **green_gates,
    )
    assert after_race.decision is CanaryDecision.CANARY_DISABLED
    assert after_race.adapter_call_count == 0
