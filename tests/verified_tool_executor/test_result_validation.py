"""Sprint 1.3.2 §41 — result validation: malformed/wrong results,
exceptions, timeouts, cancels — all normalized, no raw exception
escapes."""

import threading

from agent.verified_tool_executor.errors import (
    INVALID_TOOL_RESULT,
    TOOL_CANCELLED,
    TOOL_EXECUTION_ERROR,
    TOOL_TIMEOUT,
)
from agent.verified_tool_executor.executor import VerifiedToolExecutor
from agent.verified_tool_executor.models import (
    ExecutionStatus,
    SideEffectReport,
)
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


def test_malformed_result_non_dict_normalized():
    """§41/§9 — adapter returning a non-dict → INVALID_TOOL_RESULT."""

    class BadAdapter:
        def execute(self, context, arguments):
            return ["not", "a", "dict"]

    ex = _executor(BadAdapter())
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.FAILED
    assert res.error_code == INVALID_TOOL_RESULT
    assert res.error_class == "INVALID_TOOL_RESULT"
    assert res.retryable is False
    # TOOL_FAILED emitted, no traceback in telemetry
    failed = [e for e in ex.events if e.event_type == "TOOL_FAILED"]
    assert len(failed) == 1
    payload = failed[0].payload
    assert "traceback" not in str(payload).lower()
    assert payload["error_code"] == INVALID_TOOL_RESULT


def test_adapter_exception_normalized():
    """§41/§20 — adapter exception → FAILED TOOL_EXECUTION_ERROR,
    retryable, no raw exception object in the result."""

    class ExplodingAdapter:
        def execute(self, context, arguments):
            raise RuntimeError("boom: secret=sk-abc")

    ex = _executor(ExplodingAdapter())
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.FAILED
    assert res.error_code == TOOL_EXECUTION_ERROR
    assert res.error_class == "RuntimeError"
    assert res.retryable is True
    # the raw exception must NOT escape the public API
    assert "sk-abc" not in str(res.to_dict())
    assert "boom" not in str(res.error_class)


def test_adapter_timeout_normalized():
    """§21 — deadline breach on a READ_ONLY tool → TIMED_OUT."""

    class SlowAdapter:
        def execute(self, context, arguments):
            import time
            time.sleep(5)
            return {"ok": True}

    ex = _executor(SlowAdapter())
    res = ex.execute(make_request(timeout_ms=50))
    assert res.status is ExecutionStatus.TIMED_OUT
    assert res.error_code == TOOL_TIMEOUT
    assert res.retryable is True
    failed = [e for e in ex.events if e.event_type == "TOOL_FAILED"]
    assert len(failed) == 1
    assert failed[0].payload["error_code"] == TOOL_TIMEOUT


def test_timeout_does_not_block_forever():
    """The timeout path must not join the hung worker (1.0.2 pitfall)."""

    class HungAdapter:
        def execute(self, context, arguments):
            import time
            time.sleep(30)
            return {"ok": True}

    import time as _time

    ex = _executor(HungAdapter())
    t0 = _time.monotonic()
    res = ex.execute(make_request(timeout_ms=80))
    elapsed = _time.monotonic() - t0
    assert res.status is ExecutionStatus.TIMED_OUT
    assert elapsed < 5.0  # bounded, not blocked by the hung worker


def test_cancel_before_start():
    """§22 — cancellation before invocation → CANCELLED, calls = 0."""

    class CancelledAdapter(RecordingAdapter):
        pass

    adapter = CancelledAdapter()
    ex = _executor(adapter)
    # Pre-set the cancellation token: construct the request, then
    # cancel before execute by monkeypatching the token factory.
    token = threading.Event()
    token.set()
    ex._new_cancellation_token = lambda: token
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.CANCELLED
    assert res.error_code == TOOL_CANCELLED
    assert adapter.calls == []


def test_cancel_during_execution_read_only():
    """§22 — cooperative cancel during a READ_ONLY run → CANCELLED."""
    adapter = RecordingAdapter(output={"ok": True}, cancel_on_call=True)
    ex = _executor(adapter)
    res = ex.execute(make_request())
    # the adapter set the token during execution
    assert res.status is ExecutionStatus.CANCELLED
    assert res.error_code == TOOL_CANCELLED


def test_success_result_contract():
    """§4/§19 — successful result carries output + hash + receipt."""
    adapter = RecordingAdapter(output={"gateway_state": "running"})
    ex = _executor(adapter)
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.SUCCEEDED
    assert res.ok is True
    assert res.output == {"gateway_state": "running"}
    assert res.output_hash and len(res.output_hash) == 64
    assert res.side_effect_observed == SideEffectReport.READ_ONLY.value
    assert res.retryable is False
    assert res.execution_receipt is not None
    assert res.execution_receipt["status"] == "SUCCEEDED"
    completed = [e for e in ex.events
                 if e.event_type == "TOOL_COMPLETED"]
    assert len(completed) == 1
    assert completed[0].payload["output_hash"] == res.output_hash
    started = [e for e in ex.events if e.event_type == "TOOL_STARTED"]
    assert len(started) == 1
    assert started[0].payload["input_hash"]
    assert "arguments" not in started[0].payload  # no raw args


def test_no_raw_exception_in_any_event():
    """§35 — tracebacks/raw args never reach the event stream."""

    class ExplodingAdapter:
        def execute(self, context, arguments):
            raise ValueError("sensitive=token-xyz")

    ex = _executor(ExplodingAdapter())
    ex.execute(make_request())
    blob = "".join(str(e.to_dict()) for e in ex.events)
    assert "token-xyz" not in blob
    assert "Traceback" not in blob
