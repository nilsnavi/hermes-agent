"""Sprint 1.3.2 §42/§44 — idempotency + exactly-once.

Same (run_id, step_id, idempotency_key) twice → the adapter executes
exactly ONCE; the second call returns the prior receipt/result.
1 request → exactly 1 adapter call, no fallback adapter.
"""

from agent.verified_tool_executor.executor import VerifiedToolExecutor
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


def test_same_request_twice_executes_once():
    adapter = RecordingAdapter(output={"ok": True})
    ex = _executor(adapter)
    r1 = ex.execute(make_request())
    r2 = ex.execute(make_request())
    assert r1.status is ExecutionStatus.SUCCEEDED
    assert r2.status is ExecutionStatus.SUCCEEDED
    assert len(adapter.calls) == 1  # exactly once
    assert r2.execution_id == r1.execution_id  # prior receipt returned
    assert r2.duplicate_of == r1.execution_id


def test_same_key_different_request_id_still_dedupes():
    """Dedup is on (run_id, step_id, idempotency_key), not request_id."""
    adapter = RecordingAdapter(output={"ok": True})
    ex = _executor(adapter)
    r1 = ex.execute(make_request(request_id="req-a"))
    r2 = ex.execute(make_request(request_id="req-b"))
    assert len(adapter.calls) == 1
    assert r2.duplicate_of == r1.execution_id


def test_different_idempotency_key_executes_again():
    adapter = RecordingAdapter(output={"ok": True})
    ex = _executor(adapter)
    ex.execute(make_request(idempotency_key="k1"))
    ex.execute(make_request(idempotency_key="k2"))
    assert len(adapter.calls) == 2


def test_different_step_id_executes_again():
    adapter = RecordingAdapter(output={"ok": True})
    ex = _executor(adapter)
    ex.execute(make_request(step_id="s1"))
    ex.execute(make_request(step_id="s2"))
    assert len(adapter.calls) == 2


def test_exactly_one_adapter_call_no_fallback():
    """§44 — one request → exactly one adapter call, no fallback."""
    adapter = RecordingAdapter(output={"ok": True})
    ex = _executor(adapter)
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.SUCCEEDED
    assert len(adapter.calls) == 1
    # no second/fallback adapter was ever consulted — the registry has
    # exactly one binding for the tool
    assert len(ex._registry.names()) == 1


def test_events_single_pair():
    """One execution → exactly one TOOL_STARTED + TOOL_COMPLETED."""
    adapter = RecordingAdapter(output={"ok": True})
    ex = _executor(adapter)
    ex.execute(make_request())
    ex.execute(make_request())  # duplicate — no new events
    types = [e.event_type for e in ex.events]
    assert types.count("TOOL_STARTED") == 1
    assert types.count("TOOL_COMPLETED") == 1


def test_receipts_single_row():
    adapter = RecordingAdapter(output={"ok": True})
    ex = _executor(adapter)
    ex.execute(make_request())
    ex.execute(make_request())
    receipts = ex.receipts.all()
    assert len(receipts) == 1
    assert receipts[0].status == "SUCCEEDED"
