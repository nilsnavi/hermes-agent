import statistics
import time

from agent.multi_service_execution_canary import CanaryDecision, MultiServiceCanaryAdmission


def test_admission_p95_is_bounded_for_5000_public_api_evaluations(exact_registry, exact_request, green_gates):
    admission = MultiServiceCanaryAdmission(exact_registry)
    request = exact_request()
    samples = []
    for _ in range(5_000):
        started = time.perf_counter_ns()
        result = admission.evaluate(request, now=100.0, **green_gates)
        samples.append(time.perf_counter_ns() - started)
        assert result.decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED
    p95_ns = statistics.quantiles(samples, n=20)[18]
    assert p95_ns < 5_000_000


def test_semantic_key_is_stable_under_10000_recomputations(exact_request):
    request = exact_request()
    expected = request.semantic_key()
    started = time.perf_counter()
    values = {request.semantic_key() for _ in range(10_000)}
    elapsed = time.perf_counter() - started
    assert values == {expected}
    assert elapsed < 5.0
