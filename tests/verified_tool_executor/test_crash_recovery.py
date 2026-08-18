"""Sprint 1.3.2 §43/§32 — crash recovery.

Simulate: TOOL_STARTED emitted + receipt STARTED, then process death
before the terminal event. Reopen the store with a FRESH executor →
the orphaned execution recovers as UNKNOWN_OUTCOME and the actual
tool is NEVER called a second time.
"""

import os
import sqlite3

from agent.verified_tool_executor.executor import VerifiedToolExecutor
from agent.verified_tool_executor.models import ExecutionStatus
from agent.verified_tool_executor.registry import VerifiedToolRegistry
from agent.verified_tool_executor.receipts import (
    ExecutionReceipt,
    MemoryReceiptStore,
    SQLiteReceiptStore,
)
from tests.verified_tool_executor.conftest import (
    RecordingAdapter,
    make_request,
)


def _crashed_receipt():
    """A receipt that was STARTED but never finalized (process death)."""
    return ExecutionReceipt(
        execution_id="crashed-1",
        run_id="run-1",
        step_id="step-1",
        idempotency_key="idem-1",
        tool="runtime_status",
        input_hash="a" * 64,
        started_at="2026-08-14T12:00:00+00:00",
        status=ExecutionStatus.STARTED.value,
    )


def test_memory_store_crash_recovery_no_reexecute():
    store = MemoryReceiptStore()
    store.insert(_crashed_receipt())

    adapter = RecordingAdapter(output={"ok": True})
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter)
    ex = VerifiedToolExecutor(reg, receipts=store)

    recovered = ex.recover()
    assert len(recovered) == 1
    assert recovered[0].status == ExecutionStatus.UNKNOWN_OUTCOME.value

    # A duplicate request after recovery must NOT invoke the tool.
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.UNKNOWN_OUTCOME
    assert adapter.calls == []


def test_sqlite_store_survives_restart():
    """§15/§43 — receipts survive process restart (SQLite backend)."""
    db_path = os.path.join(os.path.dirname(__file__), "crash-test.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    try:
        # "process A": emit TOOL_STARTED receipt then die
        store_a = SQLiteReceiptStore(db_path)
        store_a.insert(_crashed_receipt())
        # simulate death — no complete() call

        # "process B": fresh executor, fresh store over the same file
        store_b = SQLiteReceiptStore(db_path)
        adapter = RecordingAdapter(output={"ok": True})
        reg = VerifiedToolRegistry()
        reg.bind("runtime_status", adapter)
        ex = VerifiedToolExecutor(reg, receipts=store_b)

        recovered = ex.recover()
        assert len(recovered) == 1
        assert recovered[0].status == ExecutionStatus.UNKNOWN_OUTCOME.value

        res = ex.execute(make_request())
        assert res.status is ExecutionStatus.UNKNOWN_OUTCOME
        assert res.error_code == "UNKNOWN_EXECUTION_OUTCOME"
        assert adapter.calls == []  # never auto-reexecute

        # The receipt row is finalized as UNKNOWN_OUTCOME in the DB.
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT status, final_status FROM "
            "agent_v2_execution_receipts WHERE execution_id=?",
            ("crashed-1",)).fetchone()
        conn.close()
        assert row == ("UNKNOWN_OUTCOME", "UNKNOWN_OUTCOME")
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_sqlite_store_duplicate_insert_rejected():
    """§13 — the SQLite backend enforces exactly-once at the storage
    level (UNIQUE constraint)."""
    db_path = os.path.join(os.path.dirname(__file__), "dup-test.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    try:
        from agent.verified_tool_executor.receipts import DuplicateExecution
        import pytest

        store = SQLiteReceiptStore(db_path)
        store.insert(_crashed_receipt())
        with pytest.raises(DuplicateExecution):
            store.insert(_crashed_receipt())
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


def test_recover_is_idempotent():
    store = MemoryReceiptStore()
    store.insert(_crashed_receipt())
    ex = VerifiedToolExecutor(
        VerifiedToolRegistry(), receipts=store)
    first = ex.recover()
    second = ex.recover()
    assert len(first) == 1
    assert second == []  # nothing left in STARTED


def test_inflight_duplicate_rejected_without_recovery():
    """A STARTED receipt (no recovery yet) → DUPLICATE_ACTION, never
    a second invocation."""
    store = MemoryReceiptStore()
    store.insert(_crashed_receipt())
    adapter = RecordingAdapter(output={"ok": True})
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter)
    ex = VerifiedToolExecutor(reg, receipts=store)
    # no recover() call — receipt still STARTED
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.REJECTED
    assert res.error_code == "DUPLICATE_ACTION"
    assert adapter.calls == []
