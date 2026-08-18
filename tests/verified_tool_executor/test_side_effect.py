"""Sprint 1.3.2 §47/§34 — side-effect mismatch.

A READ_ONLY descriptor + an adapter reporting WRITE/SYSTEM/UNKNOWN →
failure/security violation, fail closed, V2 tool route disabled.
"""

from agent.verified_tool_executor.executor import VerifiedToolExecutor
from agent.verified_tool_executor.errors import (
    TOOL_SIDE_EFFECT_VIOLATION,
)
from agent.verified_tool_executor.models import ExecutionStatus
from agent.verified_tool_executor.registry import VerifiedToolRegistry
from agent.verified_tool_executor.receipts import MemoryReceiptStore
from tests.verified_tool_executor.conftest import (
    RecordingAdapter,
    make_request,
)


def _executor(adapter):
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter)
    return VerifiedToolExecutor(reg, receipts=MemoryReceiptStore())


def test_write_report_is_security_violation():
    adapter = RecordingAdapter(output={"ok": True},
                               side_effect="WRITE")
    ex = _executor(adapter)
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.FAILED
    assert res.error_class == "SECURITY_VIOLATION"
    assert res.error_code == TOOL_SIDE_EFFECT_VIOLATION
    assert res.retryable is False
    assert res.side_effect_observed == "WRITE"


def test_system_report_is_security_violation():
    adapter = RecordingAdapter(output={"ok": True},
                               side_effect="SYSTEM")
    ex = _executor(adapter)
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.FAILED
    assert res.error_class == "SECURITY_VIOLATION"


def test_unknown_report_is_security_violation():
    adapter = RecordingAdapter(output={"ok": True},
                               side_effect="UNKNOWN")
    ex = _executor(adapter)
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.FAILED
    assert res.error_class == "SECURITY_VIOLATION"


def test_route_disabled_after_violation():
    """§34 — fail closed: the V2 tool route is disabled, so any later
    request for the same tool is REJECTED with zero adapter calls."""
    adapter = RecordingAdapter(output={"ok": True},
                               side_effect="WRITE")
    ex = _executor(adapter)
    r1 = ex.execute(make_request())
    assert r1.status is ExecutionStatus.FAILED

    # The route is disabled — resolve() now returns None.
    assert ex._registry.resolve("runtime_status") is None

    r2 = ex.execute(make_request(idempotency_key="k2",
                                 step_id="s2"))
    assert r2.status is ExecutionStatus.REJECTED
    assert r2.error_code == "TOOL_NOT_REGISTERED"
    assert len(adapter.calls) == 1  # only the first (violating) call


def test_none_report_allowed():
    adapter = RecordingAdapter(output={"ok": True},
                               side_effect="NONE")
    ex = _executor(adapter)
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.SUCCEEDED


def test_read_only_report_allowed():
    adapter = RecordingAdapter(output={"ok": True},
                               side_effect="READ_ONLY")
    ex = _executor(adapter)
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.SUCCEEDED
