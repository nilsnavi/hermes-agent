from __future__ import annotations
import json, os, time
from agent.sandbox_runtime.lock import ResourceLockManager, StaleLockDisposition


def test_stale_lock_requires_owner_dead_transaction_inactive_and_reconciled(sandbox_root):
    m=ResourceLockManager(sandbox_root); path=m._lock_path("r")
    open(path,"w").write(json.dumps({"key":"r","pid":999999,"process_nonce":"n","txid":"t","resource_identity":"r","acquired_at":0,"ttl_s":1}))
    os.utime(path,(0,0))
    assert m.assess_stale("r",owner_alive=False,transaction_active=False,resource_reconciled=True) is StaleLockDisposition.SAFE_TO_RELEASE
    assert m.assess_stale("r",owner_alive=None,transaction_active=False,resource_reconciled=True) is StaleLockDisposition.LOCK_STATE_AMBIGUOUS


def test_same_pid_different_transaction_is_not_owner(sandbox_root):
    m=ResourceLockManager(sandbox_root)
    lock=m.acquire("r","owner","tx-a",process_nonce="nonce-a",resource_identity="rid")
    assert not m.proves_owner(lock,txid="tx-b",pid=os.getpid(),process_nonce="nonce-a",resource_identity="rid")
    m.release(lock)
