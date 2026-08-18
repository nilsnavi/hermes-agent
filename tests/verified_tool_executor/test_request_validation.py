"""Sprint 1.3.2 §40 — request validation: every invalid request is
REJECTED before STARTED, adapter calls = 0."""

import pytest

from agent.verified_tool_executor.errors import (
    CAPABILITY_MISMATCH,
    INVALID_ARGUMENTS,
    POLICY_NOT_ALLOWED,
    TOOL_NOT_REGISTERED,
    TOOL_NOT_VERIFIED,
    TOOL_RISK_MISMATCH,
)
from agent.verified_tool_executor.models import ExecutionStatus
from agent.verified_tool_executor.registry import (
    VerifiedToolRegistry,
)
from agent.verified_tool_executor.receipts import MemoryReceiptStore
from tests.verified_tool_executor.conftest import (
    RecordingAdapter,
    make_request,
)


def _executor(adapter=None):
    from agent.verified_tool_executor.executor import VerifiedToolExecutor

    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter or RecordingAdapter())
    return VerifiedToolExecutor(reg, receipts=MemoryReceiptStore())


def test_unknown_tool_rejected(executor, fake_adapter):
    """§40 N1 — unknown tool → REJECTED TOOL_NOT_REGISTERED."""
    req = make_request(tool_name="definitely_not_registered")
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == TOOL_NOT_REGISTERED
    assert fake_adapter.calls == []


def test_unverified_tool_rejected():
    """§40 — a tool whose descriptor.verified=False is rejected.

    Fail-closed at BOTH layers: the CapabilityRegistry itself refuses
    to hold an unverified descriptor (§27 — "unverified routed
    capability → error" at _add), and the executor registry refuses to
    bind anything whose descriptor is not verified.
    """
    from agent.capability_router.capabilities import Capability
    from agent.capability_router.models import CapabilityDescriptor
    from agent.capability_router.registry import (
        CapabilityRegistry,
        RegistryValidationError,
    )
    from agent.verified_tool_executor.executor import VerifiedToolExecutor

    # Layer 1: the capability registry rejects an unverified
    # descriptor at construction (even validate=False — the §27 check
    # lives in _add, not in validate()).
    with pytest.raises(RegistryValidationError):
        CapabilityRegistry(
            [
                CapabilityDescriptor(
                    capability=Capability.STATUS_RUNTIME,
                    tool_name="runtime_status",
                    verified=False,
                )
            ],
            validate=False,
        )


def test_capability_mismatch_rejected(executor, fake_adapter):
    """§40 — request.capability must equal the registered capability."""
    req = make_request(capability="STATUS_GATEWAY")
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == CAPABILITY_MISMATCH
    assert fake_adapter.calls == []


def test_policy_mismatch_rejected(executor, fake_adapter):
    """§40/§45 — policy != ALLOW_V2 → REJECTED, adapter = 0."""
    req = make_request(policy_verdict="LEGACY")
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == POLICY_NOT_ALLOWED
    assert fake_adapter.calls == []


def test_policy_version_mismatch_rejected(executor, fake_adapter):
    req = make_request(policy_version="cap-policy-v0")
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == POLICY_NOT_ALLOWED
    assert fake_adapter.calls == []


def test_missing_policy_decision_id_rejected(executor, fake_adapter):
    """§45 — missing policy decision evidence → POLICY_NOT_ALLOWED."""
    req = make_request(policy_decision_id="")
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == POLICY_NOT_ALLOWED
    assert fake_adapter.calls == []


def test_invalid_arguments_rejected(executor, fake_adapter):
    """§40 — schema violation → REJECTED INVALID_ARGUMENTS, calls = 0."""
    # Default schema is EMPTY_ARGUMENT_SCHEMA — any key is invalid.
    req = make_request(arguments={"unexpected": 1})
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == INVALID_ARGUMENTS
    assert fake_adapter.calls == []


def test_invalid_timeout_rejected(executor, fake_adapter):
    req = make_request(timeout_ms=0)
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == INVALID_ARGUMENTS

    req = make_request(timeout_ms=-5)
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == INVALID_ARGUMENTS
    assert fake_adapter.calls == []


def test_missing_idempotency_key_rejected(executor, fake_adapter):
    """§14 — stable idempotency key is mandatory for READ_ONLY."""
    req = make_request(idempotency_key="")
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == INVALID_ARGUMENTS
    assert fake_adapter.calls == []


def test_expected_write_side_effect_rejected(executor, fake_adapter):
    """§6 — expected side effect must be compatible with READ_ONLY."""
    req = make_request(expected_side_effect="REVERSIBLE_WRITE")
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == TOOL_RISK_MISMATCH
    assert fake_adapter.calls == []


def test_expected_write_risk_rejected(executor, fake_adapter):
    req = make_request(expected_risk_class="IRREVERSIBLE_WRITE")
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == TOOL_RISK_MISMATCH
    assert fake_adapter.calls == []


def test_metadata_non_whitelisted_rejected(executor, fake_adapter):
    req = make_request(metadata={"api_token": "sk-secret"})
    res = executor.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == INVALID_ARGUMENTS
    assert fake_adapter.calls == []


def test_rejected_request_produces_no_events(executor):
    """REJECTED never reaches the adapter → no TOOL_* events."""
    req = make_request(tool_name="ghost")
    executor.execute(req)
    assert executor.events == []


def test_rejected_request_not_receipted(executor):
    req = make_request(tool_name="ghost")
    res = executor.execute(req)
    assert res.execution_receipt is None
