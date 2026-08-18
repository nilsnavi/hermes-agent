"""Shared fixtures for the verified_tool_executor test suite."""

import threading

import pytest

from agent.capability_router.registry import CapabilityRegistry
from agent.verified_tool_executor.adapter import AdapterResult
from agent.verified_tool_executor.boundary import NoopSystemBoundary
from agent.verified_tool_executor.executor import VerifiedToolExecutor
from agent.verified_tool_executor.models import (
    ExecutionRequest,
    SideEffectReport,
)
from agent.verified_tool_executor.receipts import MemoryReceiptStore
from agent.verified_tool_executor.registry import VerifiedToolRegistry


class RecordingAdapter:
    """Adapter that records calls and returns a canned output."""

    def __init__(self, output=None, side_effect=SideEffectReport.READ_ONLY,
                 raise_exc=None, delay_s=0.0, cancel_on_call=False):
        self.calls = []
        self.output = output if output is not None else {"ok": True}
        self.side_effect = side_effect
        self.raise_exc = raise_exc
        self.delay_s = delay_s
        self.cancel_on_call = cancel_on_call

    def execute(self, context, arguments):
        self.calls.append((context, dict(arguments)))
        if self.cancel_on_call and context.cancellation_token is not None:
            context.cancellation_token.set()
        if self.delay_s:
            import time
            time.sleep(self.delay_s)
        if self.raise_exc is not None:
            raise self.raise_exc
        return AdapterResult(
            output=dict(self.output),
            observed_side_effect=self.side_effect,
        )


@pytest.fixture
def cap_registry():
    return CapabilityRegistry()


@pytest.fixture
def registry(cap_registry):
    reg = VerifiedToolRegistry(capability_registry=cap_registry)
    return reg


def make_request(
    request_id="req-1",
    run_id="run-1",
    step_id="step-1",
    capability="STATUS_RUNTIME",
    tool_name="runtime_status",
    policy_verdict="ALLOW_V2",
    policy_version="cap-policy-v1",
    policy_decision_id="pd-1",
    arguments=None,
    timeout_ms=2000,
    idempotency_key="idem-1",
    expected_side_effect="READ_ONLY",
    expected_risk_class="READ_ONLY",
    metadata=None,
    intent="status_read",
    intent_subtype="runtime",
    operator_context=None,
) -> ExecutionRequest:
    return ExecutionRequest(
        request_id=request_id,
        run_id=run_id,
        step_id=step_id,
        intent=intent,
        intent_subtype=intent_subtype,
        capability=capability,
        tool_name=tool_name,
        policy_version=policy_version,
        policy_decision_id=policy_decision_id,
        policy_verdict=policy_verdict,
        arguments=dict(arguments or {}),
        timeout_ms=timeout_ms,
        idempotency_key=idempotency_key,
        expected_side_effect=expected_side_effect,
        expected_risk_class=expected_risk_class,
        metadata=dict(metadata or {}),
        operator_context=(
            dict(operator_context) if operator_context else None),
    )


@pytest.fixture
def request_factory():
    return make_request


@pytest.fixture
def fake_adapter():
    return RecordingAdapter()


@pytest.fixture
def bound_registry(registry, fake_adapter):
    registry.bind("runtime_status", fake_adapter)
    return registry


@pytest.fixture
def executor(bound_registry):
    ex = VerifiedToolExecutor(
        bound_registry,
        receipts=MemoryReceiptStore(),
        boundary=NoopSystemBoundary(),
    )
    return ex
