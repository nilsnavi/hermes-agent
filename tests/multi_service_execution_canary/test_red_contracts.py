"""Sprint 1.3.18 mandatory RED authority/safety contracts."""
from __future__ import annotations

import dataclasses

import pytest

from agent.multi_service_execution_canary import (
    BASELINE_SHA,
    CanaryDecision,
    CanaryRuntime,
    CanaryServiceRegistry,
    ChildExecutionIntent,
    ProductionCanaryRequest,
    build_canary_pipeline,
    build_service_set,
)


def request(**changes):
    value = ProductionCanaryRequest.for_exact_canary(
        request_id="red-1",
        baseline_sha=BASELINE_SHA,
        generation=1,
        approval_id="approval-red",
        plan_hash="plan-red",
        created_monotonic=10.0,
        expires_monotonic=1_000_000_000.0,
    )
    return dataclasses.replace(value, **changes)


def green_gates():
    return dict(
        identity_valid=True,
        graph_healthy=True,
        approval_valid=True,
        budget_available=True,
        locks_available=True,
        kill_switch_off=True,
        system_control_off=True,
        generic_service_control_denied=True,
        real_adapter_disabled=True,
    )


def test_public_authority_mint_is_impossible():
    runtime = CanaryRuntime()
    assert not hasattr(runtime, "mint")
    with pytest.raises(TypeError):
        runtime.authority_type()  # type: ignore[call-arg]


def test_caller_adapter_injection_is_rejected(tmp_path):
    with pytest.raises(TypeError):
        build_canary_pipeline(tmp_path, adapter=object())


def test_real_executor_call_is_permanently_denied(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    assert pipeline.real_execute(request(), **green_gates()) is CanaryDecision.DENIED
    assert pipeline.telemetry.real_child_adapter_calls == 0


def test_gateway_admission_is_denied(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    r = request(service_ids=("gateway", "canary-service-b"))
    assert pipeline.evaluate(r, **green_gates()).decision is CanaryDecision.DENIED
    assert pipeline.telemetry.simulated_child_calls == 0


def test_registry_drift_denies_before_adapter(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    assert pipeline.evaluate(request(registry_digest="drift"), **green_gates()).decision is CanaryDecision.REVALIDATE_REQUIRED
    assert pipeline.telemetry.simulated_child_calls == 0


def test_graph_drift_denies_before_adapter(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    assert pipeline.evaluate(request(graph_digest="drift"), **green_gates()).decision is CanaryDecision.REVALIDATE_REQUIRED
    assert pipeline.telemetry.simulated_child_calls == 0


def test_missing_child_approval_denies_globally(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    assert pipeline.evaluate(request(), **(green_gates() | {"approval_valid": False})).decision is CanaryDecision.DENIED
    assert pipeline.telemetry.simulated_child_calls == 0


def test_second_lock_unavailable_prevents_partial_execution(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    result = pipeline.evaluate(request(), **(green_gates() | {"locks_available": False}))
    assert result.decision is CanaryDecision.DENIED
    assert pipeline.telemetry.simulated_child_calls == 0


def test_double_budget_race_has_single_winner(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    results = pipeline.race(request(), contenders=100, **green_gates())
    assert sum(r.adapter_call_count > 0 for r in results) <= 1
    assert pipeline.telemetry.double_budget == 0


def test_duplicate_race_replays_without_second_adapter(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    first = pipeline.evaluate(request(), **green_gates())
    before = pipeline.telemetry.simulated_child_calls
    second = pipeline.evaluate(request(), **green_gates())
    assert first.decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED
    assert second.replayed is True
    assert pipeline.telemetry.simulated_child_calls == before


def test_child_adapter_success_is_not_global_commit(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    result = pipeline.evaluate(request(), verify_ok=False, **green_gates())
    assert result.decision is not CanaryDecision.GLOBAL_COMMITTED_SIMULATED
    assert result.real_global_commit is False


def test_unknown_is_terminal_and_never_retried(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    scenario = {"canary-service-a": "SIMULATED_UNKNOWN"}
    first = pipeline.evaluate(request(), scenario=scenario, **green_gates())
    calls = pipeline.telemetry.simulated_child_calls
    second = pipeline.evaluate(request(), scenario=scenario, **green_gates())
    assert first.decision is CanaryDecision.UNKNOWN_OUTCOME
    assert second.replayed is True
    assert pipeline.telemetry.simulated_child_calls == calls


def test_compensation_has_no_real_adapter(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    result = pipeline.evaluate(
        request(), scenario={"canary-service-b": "SIMULATED_FAILURE"}, **green_gates()
    )
    assert result.decision is CanaryDecision.COMPENSATION_REQUIRED_SIMULATED
    assert pipeline.telemetry.real_compensation_adapter_calls == 0


def test_kill_switch_cannot_be_bypassed(tmp_path):
    pipeline = build_canary_pipeline(tmp_path)
    result = pipeline.evaluate(request(), **(green_gates() | {"kill_switch_off": False}))
    assert result.decision is CanaryDecision.CANARY_DISABLED
    assert pipeline.telemetry.simulated_child_calls == 0


def test_service_set_identity_is_order_independent():
    registry = CanaryServiceRegistry()
    ab = build_service_set(("canary-service-a", "canary-service-b"), registry, baseline_sha=BASELINE_SHA, generation=1, now=1.0)
    ba = build_service_set(("canary-service-b", "canary-service-a"), registry, baseline_sha=BASELINE_SHA, generation=1, now=1.0)
    assert ab.semantic_hash() == ba.semantic_hash()
    assert ab.service_ids == ba.service_ids == ("canary-service-a", "canary-service-b")


def test_adapter_intent_is_typed_and_has_no_command_surface():
    fields = {f.name for f in dataclasses.fields(ChildExecutionIntent)}
    assert not fields.intersection({"command", "argv", "executable", "unit", "shell", "path", "address"})
