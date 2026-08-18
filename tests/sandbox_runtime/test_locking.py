"""Resource locking — one writer, bounded wait, stale recovery (Sprint 1.3.5 §14)."""

from __future__ import annotations

import os
import threading
import time

import pytest

from tests.sandbox_runtime.conftest import utcnow
from agent.sandbox_runtime.exceptions import LockConflict, LockStateAmbiguous
from agent.sandbox_runtime.lock import ResourceLockManager


def test_acquire_and_release(sandbox_root):
    mgr = ResourceLockManager(sandbox_root)
    lock = mgr.acquire("file://data/x.txt", owner="run-1", txid="tx-1",
                       ttl_s=60, wait_s=0.2)
    assert lock is not None
    mgr.release(lock)


def test_second_writer_blocked(sandbox_root):
    mgr = ResourceLockManager(sandbox_root)
    lock = mgr.acquire("file://data/x.txt", owner="run-1", txid="tx-1",
                       ttl_s=60, wait_s=0.2)
    try:
        with pytest.raises(LockConflict):
            mgr.acquire("file://data/x.txt", owner="run-2", txid="tx-2",
                        ttl_s=60, wait_s=0.1)
    finally:
        mgr.release(lock)


def test_different_resource_not_blocked(sandbox_root):
    mgr = ResourceLockManager(sandbox_root)
    lock1 = mgr.acquire("file://a", owner="r1", txid="t1", ttl_s=60, wait_s=0.2)
    try:
        lock2 = mgr.acquire("file://b", owner="r1", txid="t2", ttl_s=60, wait_s=0.2)
        mgr.release(lock2)
    finally:
        mgr.release(lock1)


def test_lock_released_after_release(sandbox_root):
    mgr = ResourceLockManager(sandbox_root)
    lock = mgr.acquire("file://z", owner="r1", txid="t1", ttl_s=60, wait_s=0.2)
    mgr.release(lock)
    lock2 = mgr.acquire("file://z", owner="r2", txid="t2", ttl_s=60, wait_s=0.2)
    mgr.release(lock2)


def test_expired_lock_requires_proof_before_recovery(sandbox_root, monkeypatch):
    mgr = ResourceLockManager(sandbox_root)
    lock = mgr.acquire("file://stale", owner="run-dead", txid="tx-dead",
                       ttl_s=60, wait_s=0.2)
    # simulate the owner dying WITHOUT releasing: close the fd but
    # leave the lock file in place, then age it past the TTL
    if lock._fd is not None:
        os.close(lock._fd)
        lock._fd = None
    old = time.time() - 3600
    os.utime(lock.path, (old, old))
    # Sprint 1.3.6: TTL alone is not enough to prove owner death,
    # transaction inactivity, and reconciled resource state.
    with pytest.raises(LockStateAmbiguous):
        mgr.acquire("file://stale", owner="run-new", txid="tx-new",
                    ttl_s=60, wait_s=0.2, recover_stale=True)


def test_concurrent_writers_one_wins(sandbox_root):
    mgr = ResourceLockManager(sandbox_root)
    winner = []
    blocked = []
    barrier = threading.Barrier(4)

    def _try(owner):
        barrier.wait()  # all four start at the same instant
        try:
            lk = mgr.acquire("file://race", owner=owner, txid=f"tx-{owner}",
                             ttl_s=60, wait_s=0.05)
            if lk is not None:
                time.sleep(0.3)  # hold longer than every wait budget
                mgr.release(lk)
                winner.append(owner)
        except LockConflict:
            blocked.append(owner)

    threads = [threading.Thread(target=_try, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # one writer wins; the other three hit their 0.05s wait budget
    # while the winner holds the lock for 0.3s
    assert len(winner) == 1
    assert len(blocked) == 3


def test_lock_has_owner_identity(sandbox_root):
    mgr = ResourceLockManager(sandbox_root)
    lock = mgr.acquire("file://owner", owner="run-42", txid="tx-42",
                       ttl_s=60, wait_s=0.2)
    assert lock.owner == "run-42"
    assert lock.txid == "tx-42"
    mgr.release(lock)


def test_no_global_lock(sandbox_root):
    # acquiring locks on two unrelated resources must not serialize
    mgr = ResourceLockManager(sandbox_root)
    l1 = mgr.acquire("file://one", owner="r", txid="t", ttl_s=60, wait_s=0.2)
    l2 = mgr.acquire("file://two", owner="r", txid="t2", ttl_s=60, wait_s=0.2)
    mgr.release(l1)
    mgr.release(l2)
