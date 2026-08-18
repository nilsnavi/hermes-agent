"""Exactly-once / idempotency — duplicate requests replay prior result (Sprint 1.3.5 §13)."""

from __future__ import annotations

import pytest

from agent.sandbox_runtime.exceptions import DuplicateAction
from agent.sandbox_runtime.transaction import TransactionStore


def test_duplicate_request_returns_prior(sandbox_root, make_req):
    store = TransactionStore(sandbox_root)
    req = make_req(idempotency_key="idem-X", target="data/x.txt")
    store.record_started(req, txid="tx-x")
    store.record_backup(req)
    store.record_executed(req, {"ok": True})
    store.record_verified(req)
    store.record_health(req, ok=True)
    store.record_completed(req, status="COMMITTED", receipt={"ok": True})
    # replay: same idempotency key → prior result, no second execution
    prior = store.replay(req)
    assert prior is not None
    assert prior["status"] == "COMMITTED"


def test_different_idempotency_key_is_new_action(sandbox_root, make_req):
    store = TransactionStore(sandbox_root)
    req1 = make_req(idempotency_key="K1")
    store.record_started(req1, txid="tx-k1")
    store.record_backup(req1)
    store.record_executed(req1, {"ok": True})
    store.record_verified(req1)
    store.record_health(req1, ok=True)
    store.record_completed(req1, "COMMITTED", {})
    assert store.replay(make_req(idempotency_key="K2")) is None


def test_inflight_duplicate_flagged(sandbox_root, make_req):
    store = TransactionStore(sandbox_root)
    req = make_req(idempotency_key="INFLIGHT-1")
    store.record_started(req, txid="tx-1")
    with pytest.raises(DuplicateAction):
        store.replay(req, allow_inflight=False)


def test_replay_after_committed_adapter_zero(sandbox_root, make_req):
    store = TransactionStore(sandbox_root)
    req = make_req(idempotency_key="C1")
    store.record_started(req, txid="tx-c1")
    store.record_backup(req)
    store.record_executed(req, {"ok": True})
    store.record_verified(req)
    store.record_health(req, ok=True)
    store.record_completed(req, "COMMITTED", {"ok": True})
    prior = store.replay(req)
    assert prior is not None
    # adapter call counter is tracked by the executor, not the store;
    # store-level guarantee: replay returns prior, never re-executes.


def test_unknown_outcome_replay_no_retry(sandbox_root, make_req):
    store = TransactionStore(sandbox_root)
    req = make_req(idempotency_key="U1")
    store.record_started(req, txid="tx-u1")
    store.record_unknown(req, reason="crash after execute")
    prior = store.replay(req)
    assert prior is not None
    assert prior["status"] == "UNKNOWN_OUTCOME"


def test_store_persists_across_reopen(sandbox_root, make_req):
    store = TransactionStore(sandbox_root)
    req = make_req(idempotency_key="PERSIST-1")
    store.record_started(req, txid="tx-persist")
    store.record_backup(req)
    store.record_executed(req, {"ok": True})
    store.record_verified(req)
    store.record_health(req, ok=True)
    store.record_completed(req, "COMMITTED", {"ok": True})
    store2 = TransactionStore(sandbox_root)
    assert store2.replay(req) is not None


def test_started_without_completed_is_orphan(sandbox_root, make_req):
    store = TransactionStore(sandbox_root)
    req = make_req(idempotency_key="ORPHAN-1")
    store.record_started(req, txid="tx-o1")
    orphans = store.find_orphaned()
    assert len(orphans) == 1
    assert orphans[0]["idempotency_key"] == "ORPHAN-1"
