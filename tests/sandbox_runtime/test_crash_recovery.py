"""Crash recovery — incomplete transactions, no auto retry (Sprint 1.3.5 §24/§44)."""

from __future__ import annotations

import os

import pytest

from tests.sandbox_runtime.conftest import make_request, utcnow
from agent.sandbox_runtime.recovery import (
    CrashPoint,
    classify_incomplete,
    recover_transactions,
)
from agent.sandbox_runtime.transaction import TransactionStore


def _started_store(sandbox_root, key="CRASH-1", txid="tx-crash"):
    store = TransactionStore(sandbox_root)
    req = make_request(idempotency_key=key)
    store.record_started(req, txid=txid)
    return store, req


def test_orphan_started_classified_unknown(sandbox_root):
    store, req = _started_store(sandbox_root)
    tx = store.find_orphaned()[0]
    verdict = classify_incomplete(tx)
    assert verdict == "UNKNOWN_OUTCOME"


def test_no_automatic_retry_on_unknown(sandbox_root):
    store, req = _started_store(sandbox_root)
    recovered = recover_transactions(sandbox_root, auto_retry=False)
    # must NOT be executed again; flagged for manual review
    assert recovered
    assert recovered[0]["disposition"] == "MANUAL_REVIEW_REQUIRED"
    # the store still holds the orphan — nothing re-ran
    assert len(store.find_orphaned()) == 1


def test_completed_transaction_not_touched(sandbox_root, make_req):
    store = TransactionStore(sandbox_root)
    req = make_req(idempotency_key="DONE-1")
    store.record_started(req, txid="tx-done")
    store.record_backup(req)
    store.record_executed(req, {"ok": True})
    store.record_verified(req)
    store.record_health(req, ok=True)
    store.record_completed(req, "COMMITTED", {"ok": True})
    recovered = recover_transactions(sandbox_root, auto_retry=False)
    assert recovered == []


def test_crash_after_execute_disposition(sandbox_root):
    store, req = _started_store(sandbox_root, key="CRASH-AFTER-EXEC")
    tx = store.find_orphaned()[0]
    verdict = classify_incomplete(tx)
    assert verdict == "UNKNOWN_OUTCOME"
    assert store.replay(req)["status"] == "UNKNOWN_OUTCOME"


def test_crash_recovery_requires_manual_review_flag(sandbox_root):
    _, req = _started_store(sandbox_root, key="MR-1")
    recovered = recover_transactions(sandbox_root, auto_retry=False)
    assert recovered[0]["manual_review_required"] is True


def test_crash_point_enum_surface():
    points = {p.value for p in CrashPoint}
    assert "CRASH_AFTER_EXECUTE" in points
    assert "FAIL_DURING_ROLLBACK" in points


def test_reopen_store_recovers_state(sandbox_root):
    store1 = TransactionStore(sandbox_root)
    req = make_request(idempotency_key="REOPEN-1")
    store1.record_started(req, txid="tx-reopen")
    # process B reopens
    store2 = TransactionStore(sandbox_root)
    orphans = store2.find_orphaned()
    assert len(orphans) == 1
    assert orphans[0]["idempotency_key"] == "REOPEN-1"


def test_tool_started_without_completed_never_retried(sandbox_root):
    store, req = _started_store(sandbox_root, key="NO-RETRY-1")
    tx = store.find_orphaned()[0]
    assert tx["tool_started"] is True
    assert tx["tool_completed"] is False
    verdict = classify_incomplete(tx)
    assert verdict == "UNKNOWN_OUTCOME"
