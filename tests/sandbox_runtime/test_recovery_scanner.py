from __future__ import annotations
from tests.sandbox_runtime.conftest import make_request
from agent.sandbox_runtime.transaction import TransactionStore
from agent.sandbox_runtime.recovery import scan_incomplete_transactions, RecoveryDisposition


def test_scanner_is_bounded_deterministic_and_read_only(sandbox_root):
    store=TransactionStore(sandbox_root)
    for i in range(12):
        req=make_request(run_id=f"r{i}",idempotency_key=f"i{i}"); store.record_started(req,f"t{i}")
    before=open(store._path(),"rb").read()
    rows=scan_incomplete_transactions(sandbox_root,limit=5)
    after=open(store._path(),"rb").read()
    assert len(rows)==5 and [r.transaction_id for r in rows]==sorted(r.transaction_id for r in rows)
    assert before==after
    assert all(r.disposition is RecoveryDisposition.MANUAL_REVIEW_REQUIRED for r in rows)
