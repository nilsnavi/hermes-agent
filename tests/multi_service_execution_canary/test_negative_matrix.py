import pytest

from agent.multi_service_execution_canary import CanaryDecision, build_canary_pipeline


DENIED_SERVICE_IDS = (
    "gateway", "scheduler", "provider", "database", "db", "network", "auth", "security",
    "docker", "container", "ssh", "unknown", "unregistered", "systemd", "root",
)
DENY_VARIANTS = ("left", "right", "single", "triple", "duplicate")
DENY_MATRIX = tuple((service_id, variant) for service_id in DENIED_SERVICE_IDS for variant in DENY_VARIANTS)
DENIED_OPERATIONS = (
    "SYSTEM_CONTROL", "SERVICE_CONTROL", "restart", "reload", "stop", "start",
    "signal", "kill", "pkill", "raw subprocess", "shell=True", "os.system",
    "caller adapter", "caller executable", "dynamic import executor",
)
DENIED_BLASTS = ("HOST", "NETWORK", "UNKNOWN")


def denied_set(service_id, variant):
    if variant == "left":
        return (service_id, "canary-service-b")
    if variant == "right":
        return ("canary-service-a", service_id)
    if variant == "single":
        return (service_id,)
    if variant == "triple":
        return ("canary-service-a", "canary-service-b", service_id)
    return (service_id, service_id)


@pytest.mark.parametrize(("service_id", "variant"), DENY_MATRIX, ids=[f"{service_id}-{variant}" for service_id, variant in DENY_MATRIX])
def test_explicit_75_case_service_set_deny_matrix(tmp_path, exact_request, green_gates, fixed_clock, service_id, variant):
    pipeline = build_canary_pipeline(tmp_path / f"{service_id}-{variant}", clock=fixed_clock)
    result = pipeline.evaluate(exact_request(service_ids=denied_set(service_id, variant)), **green_gates)
    assert result.decision is CanaryDecision.DENIED
    assert result.reason == "service-set"
    assert result.adapter_call_count == 0
    assert pipeline.telemetry.simulated_child_calls == 0
    assert pipeline.telemetry.real_child_adapter_calls == 0


def test_negative_matrix_has_at_least_75_explicit_cases():
    assert len(DENY_MATRIX) + len(DENIED_OPERATIONS) + len(DENIED_BLASTS) + 2 >= 75
    assert len(set(DENY_MATRIX)) == 75


@pytest.mark.parametrize("operation", DENIED_OPERATIONS)
def test_forbidden_operation_is_denied_before_adapter(tmp_path, exact_request, green_gates, fixed_clock, operation):
    pipeline = build_canary_pipeline(tmp_path / operation.replace("/", "_"), clock=fixed_clock)
    result = pipeline.evaluate(exact_request(operation=operation), **green_gates)
    assert result.decision is CanaryDecision.DENIED
    assert result.adapter_call_count == 0
    assert pipeline.telemetry.real_child_adapter_calls == 0


@pytest.mark.parametrize("blast", DENIED_BLASTS)
def test_forbidden_blast_is_denied_before_adapter(tmp_path, exact_request, green_gates, fixed_clock, blast):
    pipeline = build_canary_pipeline(tmp_path / blast, clock=fixed_clock)
    result = pipeline.evaluate(exact_request(blast=blast), **green_gates)
    assert result.decision is CanaryDecision.DENIED
    assert result.adapter_call_count == 0


@pytest.mark.parametrize("gate", ["system_control_off", "generic_service_control_denied"])
def test_control_authority_gate_is_denied(tmp_path, exact_request, green_gates, fixed_clock, gate):
    pipeline = build_canary_pipeline(tmp_path / gate, clock=fixed_clock)
    result = pipeline.evaluate(exact_request(), **(green_gates | {gate: False}))
    assert result.decision is CanaryDecision.DENIED
    assert result.adapter_call_count == 0
