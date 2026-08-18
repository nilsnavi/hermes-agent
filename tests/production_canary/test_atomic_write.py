"""Sprint 1.3.7 §15/§16/§17 — atomic write, idempotency, lock."""
from __future__ import annotations

import os

import pytest

from agent.production_canary.atomic_write import (atomic_write, content_hash,
                                                  idempotency_key,
                                                  IdempotencyRegistry)
from agent.production_canary.lock import LockConflict, LockManager


def test_atomic_write_creates_content_and_mode(tmp_path):
    target = tmp_path / "canary.json"
    data = b'{"schema_version":1}'
    atomic_write(str(target), data, mode=0o600)
    assert target.read_bytes() == data
    assert (target.stat().st_mode & 0o777) == 0o600


def test_atomic_write_no_leftover_tmp(tmp_path):
    target = tmp_path / "canary.json"
    atomic_write(str(target), b"x" * 100, mode=0o600)
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith(".canary-") and p.endswith(".tmp")]
    assert leftovers == []


def test_idempotency_key_deterministic():
    a = idempotency_key(baseline_sha="b", transaction_id="t", target_fingerprint="f",
                        expected_after_hash="h")
    b = idempotency_key(baseline_sha="b", transaction_id="t", target_fingerprint="f",
                        expected_after_hash="h")
    assert a == b
    c = idempotency_key(baseline_sha="B", transaction_id="t", target_fingerprint="f",
                        expected_after_hash="h")
    assert a != c


def test_idempotency_registry_duplicate_returns_prior(tmp_path):
    reg = IdempotencyRegistry(str(tmp_path / "idem.json"))
    key = "k1"
    assert reg.lookup(key) is None
    reg.record(key, {"status": "COMMITTED"})
    prior = reg.lookup(key)
    assert prior["status"] == "COMMITTED"


def test_lock_exclusive(tmp_path):
    lm = LockManager(str(tmp_path / "locks"), ttl_s=100)
    key = "res:1"
    l1 = lm.acquire(key, "tx-a")
    with pytest.raises(LockConflict):
        lm.acquire(key, "tx-b", wait_s=0.1)
    lm.release(l1)
    l2 = lm.acquire(key, "tx-c", wait_s=0.2)  # now free
    lm.release(l2)
