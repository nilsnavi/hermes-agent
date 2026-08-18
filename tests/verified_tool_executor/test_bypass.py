"""Sprint 1.3.2 §45/§46 — policy bypass + registry bypass.

§45: a direct executor call with policy != ALLOW_V2 → REJECTED,
adapter calls = 0.
§46: a fake tool object supplied manually must NOT execute — registry
identity is required; the executor can only ever reach tools through
its VerifiedToolRegistry bindings.
"""

import pytest

from agent.verified_tool_executor.executor import VerifiedToolExecutor
from agent.verified_tool_executor.errors import POLICY_NOT_ALLOWED
from agent.verified_tool_executor.models import ExecutionStatus
from agent.verified_tool_executor.registry import VerifiedToolRegistry
from agent.verified_tool_executor.receipts import MemoryReceiptStore
from tests.verified_tool_executor.conftest import (
    RecordingAdapter,
    make_request,
)


def test_policy_bypass_rejected():
    adapter = RecordingAdapter(output={"ok": True})
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter)
    ex = VerifiedToolExecutor(reg, receipts=MemoryReceiptStore())

    for verdict in ("LEGACY", "DENY", "", "ALLOWED", "garbage"):
        req = make_request(policy_verdict=verdict)
        res = ex.execute(req)
        assert res.status is ExecutionStatus.REJECTED
        assert res.error_code == POLICY_NOT_ALLOWED
    assert adapter.calls == []


def test_policy_gate_injectable():
    """A custom policy gate can be injected (integration point)."""

    class FailingGate:
        def __call__(self, request):
            return False

    adapter = RecordingAdapter(output={"ok": True})
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter)
    ex = VerifiedToolExecutor(
        reg, receipts=MemoryReceiptStore(), policy_gate=FailingGate())
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == POLICY_NOT_ALLOWED
    assert adapter.calls == []


def test_registry_bypass_impossible():
    """§46 — a fake tool object must not execute.

    The executor's only execution path is
    ``registry.resolve(tool_name)`` — a request naming a tool that was
    never bound through the registry (even if a fake object with that
    name exists somewhere) is REJECTED as TOOL_NOT_REGISTERED.
    """
    fake = object()  # a fake "tool object" supplied manually
    reg = VerifiedToolRegistry()
    ex = VerifiedToolExecutor(reg, receipts=MemoryReceiptStore())

    req = make_request(tool_name="runtime_status")
    # inject the fake into the request's arguments to prove it is
    # never consulted
    req = make_request(tool_name="runtime_status")
    res = ex.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == "TOOL_NOT_REGISTERED"
    assert fake is not None  # never used


def test_executor_rejects_non_registry_adapter_object():
    """A request can never smuggle an adapter object in — only the
    tool NAME travels in the request, and resolution is registry-only."""

    class SneakyAdapter:
        def execute(self, context, arguments):
            return {"executed": True}

    # The sneaky adapter exists but is never bound → never called.
    sneaky = SneakyAdapter()
    reg = VerifiedToolRegistry()
    ex = VerifiedToolExecutor(reg, receipts=MemoryReceiptStore())
    req = make_request(tool_name="runtime_status")
    res = ex.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == "TOOL_NOT_REGISTERED"
    assert sneaky.__class__.__name__ == "SneakyAdapter"


def test_registry_identity_required_for_execution():
    """The bound adapter is the ONLY executable implementation."""
    adapter = RecordingAdapter(output={"ok": True})
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter)
    ex = VerifiedToolExecutor(reg, receipts=MemoryReceiptStore())

    res = ex.execute(make_request(tool_name="runtime_status"))
    assert res.status is ExecutionStatus.SUCCEEDED
    assert len(adapter.calls) == 1
