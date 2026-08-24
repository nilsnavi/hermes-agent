import os
import threading

from agent.service_restart_policy.lock import HardenedServiceLock


def test_expired_lease_cannot_evict_live_same_process_identity(tmp_path):
    starts = {10: "start-a", 11: "start-b"}
    lock = HardenedServiceLock(
        tmp_path, process_start=starts.get, ttl=10, max_clock_drift=2
    )
    assert lock.acquire("svc", 10, "start-a", "owner", now=100)
    assert not lock.acquire("svc", 11, "start-b", "contender", now=111)
    holder = lock.holder("svc")
    assert holder["pid"] == 10
    assert holder["start"] == "start-a"
    assert holder["nonce"] == "owner"


def test_expired_dead_owner_requires_safe_recovery_and_no_active_transaction(tmp_path):
    starts = {1: "old", 2: "new"}
    active = {"value": True}
    lock = HardenedServiceLock(
        tmp_path,
        process_start=starts.get,
        ttl=10,
        transaction_active=lambda service, tx: active["value"],
    )
    assert lock.acquire("svc", 1, "old", "n1", 100, "old-tx")
    starts.pop(1)
    assert not lock.acquire("svc", 2, "new", "n2", 111, "new-tx")
    active["value"] = False
    assert lock.acquire("svc", 2, "new", "n2", 111, "new-tx")


def test_same_pid_different_start_identity_uses_pid_reuse_recovery_path(tmp_path):
    starts = {10: "old"}
    lock = HardenedServiceLock(tmp_path, process_start=starts.get, ttl=10)
    assert lock.acquire("svc", 10, "old", "n1", 100, "old-tx")
    starts[10] = "new"
    assert not lock.acquire("svc", 10, "new", "n2", 109, "new-tx")
    assert lock.acquire("svc", 10, "new", "n2", 111, "new-tx")


def test_unknown_owner_liveness_fails_closed(tmp_path):
    starts = {1: "old", 2: "new"}
    lock = HardenedServiceLock(
        tmp_path,
        process_start=starts.get,
        owner_liveness=lambda pid, start: "UNKNOWN",
        ttl=10,
    )
    assert lock.acquire("svc", 1, "old", "n1", 100, "old-tx")
    assert not lock.acquire("svc", 2, "new", "n2", 111, "new-tx")


def test_only_exact_live_owner_can_renew_lease(tmp_path):
    # A4: renewal is live-owner bound.  Only the actual current process (the
    # one that acquired the lease) may renew; replaying the record tuple from
    # another process must be denied even with a correct pid/start/nonce.
    owner_pid = os.getpid()
    starts = {owner_pid: "start", owner_pid + 1: "start"}
    lock = HardenedServiceLock(tmp_path, process_start=starts.get, ttl=10)
    assert lock.acquire("svc", owner_pid, "start", "nonce", 100, "tx")
    # Wrong nonce / transaction: tuple mismatch.
    assert not lock.renew("svc", "tx", owner_pid, "start", "wrong", 105)
    assert not lock.renew("svc", "wrong-tx", owner_pid, "start", "nonce", 105)
    # Foreign PID: the renewing process is not the recorded owner -> DENY.
    assert not lock.renew("svc", "tx", owner_pid + 1, "start", "nonce", 105)
    # Same PID but different start identity -> liveness/identity mismatch -> DENY.
    assert not lock.renew("svc", "tx", owner_pid, "different-start", "nonce", 105)
    # Exact live owner renews successfully.
    assert lock.renew("svc", "tx", owner_pid, "start", "nonce", 105)
    assert lock.holder("svc")["heartbeat"] == 1


def test_two_concurrent_takeovers_never_create_two_owners(tmp_path):
    starts = {1: "old", 2: "two", 3: "three"}
    seed = HardenedServiceLock(tmp_path, process_start=starts.get, ttl=10)
    assert seed.acquire("svc", 1, "old", "old", 100, "old-tx")
    starts.pop(1)
    barrier = threading.Barrier(2)
    results = []

    def contender(pid, start, nonce):
        lock = HardenedServiceLock(tmp_path, process_start=starts.get, ttl=10)
        barrier.wait()
        results.append(lock.acquire("svc", pid, start, nonce, 111, f"tx-{pid}"))

    threads = [
        threading.Thread(target=contender, args=(2, "two", "n2")),
        threading.Thread(target=contender, args=(3, "three", "n3")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False, True]
