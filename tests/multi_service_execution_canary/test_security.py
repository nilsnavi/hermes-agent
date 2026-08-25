import copy
import dataclasses
import pickle

import pytest

import agent.multi_service_execution_canary as public_api
from agent.multi_service_execution_canary import CanaryDecision, CanaryRuntime, ChildExecutionIntent, ProductionCanaryAuthority, build_canary_pipeline


def test_authority_cannot_be_constructed_copied_or_replayed_after_pickle(exact_request):
    with pytest.raises(TypeError, match="runtime-owned"):
        ProductionCanaryAuthority()
    runtime = CanaryRuntime()
    authority = runtime._issue(exact_request())
    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.loads(pickle.dumps(authority))
    with pytest.raises(TypeError):
        copy.copy(authority)
    assert runtime._consume(authority, exact_request()) is True
    assert runtime._consume(authority, exact_request()) is False


def test_public_api_does_not_export_adapter_or_store_capabilities():
    assert "CanaryChildExecutionAdapter" not in public_api.__all__
    assert "CanaryStore" not in public_api.__all__
    assert not hasattr(public_api, "CanaryChildExecutionAdapter")
    assert not hasattr(public_api, "CanaryStore")


def test_request_and_child_intent_have_no_command_or_system_control_fields():
    forbidden = {"command", "argv", "shell", "unit", "signal", "pid", "path", "address", "systemctl"}
    request_fields = {field.name for field in dataclasses.fields(public_api.ProductionCanaryRequest)}
    intent_fields = {field.name for field in dataclasses.fields(ChildExecutionIntent)}
    assert request_fields.isdisjoint(forbidden)
    assert intent_fields.isdisjoint(forbidden)


def test_caller_cannot_inject_adapter_runtime_or_registry(tmp_path):
    for argument in ("adapter", "runtime", "registry"):
        with pytest.raises(TypeError):
            build_canary_pipeline(tmp_path / argument, **{argument: object()})


def test_flags_off_denies_before_authority_or_adapter(tmp_path, exact_request, green_gates, fixed_clock):
    pipeline = build_canary_pipeline(
        tmp_path,
        clock=fixed_clock,
        env={"HERMES_MULTI_SERVICE_CANARY_V2_ENABLED": "false"},
    )
    result = pipeline.evaluate(exact_request(), **green_gates)
    assert result.decision is CanaryDecision.CANARY_DISABLED
    assert result.adapter_call_count == 0
    assert pipeline.telemetry.simulated_child_calls == 0
    assert pipeline.telemetry.real_child_adapter_calls == 0
