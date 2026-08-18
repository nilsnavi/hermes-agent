"""Sprint 1.3.2 §48/§25 — boundary hook.

The NoopSystemBoundary is consulted for EVERY execution. A mock deny
boundary → REJECTED, adapter call = 0 — proving the Sprint 1.3.3
insertion point.
"""

from agent.verified_tool_executor.boundary import (
    DenySystemBoundary,
    NoopSystemBoundary,
)
from agent.verified_tool_executor.executor import VerifiedToolExecutor
from agent.verified_tool_executor.errors import BOUNDARY_REJECTED
from agent.verified_tool_executor.models import ExecutionStatus
from agent.verified_tool_executor.registry import VerifiedToolRegistry
from agent.verified_tool_executor.receipts import MemoryReceiptStore
from tests.verified_tool_executor.conftest import (
    RecordingAdapter,
    make_request,
)


class CountingNoopBoundary(NoopSystemBoundary):
    """Noop boundary that records consultations."""

    def __init__(self):
        self.consultations = 0

    def authorize(self, request):
        self.consultations += 1
        return super().authorize(request)


def test_noop_boundary_consulted_every_execution():
    adapter = RecordingAdapter(output={"ok": True})
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter)
    boundary = CountingNoopBoundary()
    ex = VerifiedToolExecutor(
        reg, receipts=MemoryReceiptStore(), boundary=boundary)

    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.SUCCEEDED
    assert boundary.consultations == 1
    assert len(adapter.calls) == 1


def test_noop_boundary_consulted_even_on_reject():
    """The boundary hook sits before argument validation — it is
    consulted for every execution attempt that passes the policy
    gate, including ones later rejected on args."""
    adapter = RecordingAdapter(output={"ok": True})
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter)
    boundary = CountingNoopBoundary()
    ex = VerifiedToolExecutor(
        reg, receipts=MemoryReceiptStore(), boundary=boundary)

    res = ex.execute(make_request(arguments={"bad": 1}))
    assert res.status is ExecutionStatus.REJECTED
    assert boundary.consultations == 1
    assert adapter.calls == []


def test_deny_boundary_rejects_without_adapter_call():
    adapter = RecordingAdapter(output={"ok": True})
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter)
    ex = VerifiedToolExecutor(
        reg, receipts=MemoryReceiptStore(),
        boundary=DenySystemBoundary(reason_code="TEST_DENY"))

    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == BOUNDARY_REJECTED
    assert res.error_class == BOUNDARY_REJECTED
    assert adapter.calls == []


def test_deny_boundary_no_events_no_receipts():
    adapter = RecordingAdapter(output={"ok": True})
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter)
    ex = VerifiedToolExecutor(
        reg, receipts=MemoryReceiptStore(),
        boundary=DenySystemBoundary())
    res = ex.execute(make_request())
    assert res.execution_receipt is None
    assert ex.events == []
    assert ex.receipts.all() == []


def test_boundary_decision_model():
    d = DenySystemBoundary().authorize(make_request())
    assert d.allow is False
    assert d.reason_code == "BOUNDARY_DENIED"
    assert d.boundary_version == "deny-test-v0"
    n = NoopSystemBoundary().authorize(make_request())
    assert n.allow is True
    assert n.boundary_version == "noop-v0"
