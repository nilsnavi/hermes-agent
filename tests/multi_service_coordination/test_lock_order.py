from __future__ import annotations

import hashlib

from agent.multi_service_coordination.lock_order import (
    CanonicalLockSet,
    canonical_lock_order,
)

A = "fake-aux-a"
B = "fake-aux-b"
C = "hermes-aux-canary"


def test_canonical_order_is_deterministic_and_request_order_independent():
    a = canonical_lock_order(["fake-aux-a", "fake-aux-b", "hermes-aux-canary"])
    b = canonical_lock_order(["hermes-aux-canary", "fake-aux-b", "fake-aux-a"])
    assert a == b  # caller request order must not matter


def test_canonical_order_is_sorted_by_identity_digest():
    sids = ["fake-aux-a", "fake-aux-b"]
    expected = sorted(sids, key=lambda s: hashlib.sha256(s.encode()).hexdigest())
    assert canonical_lock_order(sids) == expected


def test_deadlock_attempt_yields_single_winner_not_two_writers():
    locks = CanonicalLockSet()
    # two concurrent transactions over the same A+B set
    r1 = locks.acquire_many("tx-X", ["fake-aux-a", "fake-aux-b"])
    if r1 is not None:
        r2 = locks.acquire_many("tx-Y", ["fake-aux-b", "fake-aux-a"])
        assert r2 is None  # Y cannot double-write services X holds
        assert locks.writer_count("fake-aux-a") == 1
        assert locks.writer_count("fake-aux-b") == 1
        locks.release_many("tx-X", r1)
    else:
        r2 = locks.acquire_many("tx-Y", ["fake-aux-b", "fake-aux-a"])
        assert r2 is not None
        locks.release_many("tx-Y", r2)


def test_at_most_one_active_writer_per_service():
    locks = CanonicalLockSet()
    got = locks.acquire_many("tx-1", ["fake-aux-a"])
    assert got is not None
    assert not locks.acquire_many("tx-2", ["fake-aux-a"])  # second writer refused
    assert locks.active_writers()["fake-aux-a"] == "tx-1"
    locks.release_many("tx-1", ["fake-aux-a"])
    assert locks.acquire_many("tx-3", ["fake-aux-a"]) is not None


def test_release_many_only_removes_own_writers():
    locks = CanonicalLockSet()
    locks.acquire_many("tx-1", ["fake-aux-a", "fake-aux-b"])
    locks.release_many("tx-EVIL", ["fake-aux-a"])  # foreign release must not remove
    assert "fake-aux-a" in locks.active_writers()
    locks.release_many("tx-1", ["fake-aux-a", "fake-aux-b"])
    assert locks.active_writers() == {}  # all released


def test_no_deadlock_observed_in_overlapping_sets():
    locks = CanonicalLockSet()
    a = locks.acquire_many("tx-1", ["fake-aux-a", "fake-aux-b"])
    assert a is not None
    # (a,b) vs (b,c): canonical shared order; contention on existing holder
    # returns None (waits-free refuse), never a deadlock (would hang).
    assert locks.acquire_many("tx-2", ["fake-aux-b", "hermes-aux-canary"]) is None
    locks.release_many("tx-1", a)


def test_abc_vs_cba_produce_identical_canonical_order():
    # Sprint 1.3.15.1 §9 fresh proof — 3-service sets, caller-independent.
    locks = CanonicalLockSet()
    o1 = locks.canonical([A, B, C])
    o2 = locks.canonical([C, B, A])
    assert list(o1) == list(o2)


def test_live_owner_takeover_denied():
    # §11 live-owner takeover must be DENIED: an active writer is never stolen.
    locks = CanonicalLockSet()
    assert locks.acquire_many("tx-owner", [A, B]) is not None
    assert locks.acquire_many("tx-intruder", [A, B]) is None       # takeover DENY
    assert locks.active_writers().get(A) == "tx-owner"             # still owned
    assert locks.active_writers().get(B) == "tx-owner"
    locks.release_many("tx-owner", [A, B])


def test_spoofed_owner_release_denied():
    # §11 spoofed owner must not clear another holder's write lease.
    locks = CanonicalLockSet()
    assert locks.acquire_many("tx-real", [A]) is not None
    locks.release_many("tx-forged", [A])                            # spoofed release DENY
    assert locks.active_writers().get(A) == "tx-real"               # lease intact
    locks.release_many("tx-real", [A])