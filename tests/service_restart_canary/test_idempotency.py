"""Test durable idempotency: exactly-once, replay -> DUPLICATE."""
import tempfile, os
from agent.service_restart_canary.idempotency import DurableIdempotencyStore, idempotency_key


def test_key_stable():
    k1 = idempotency_key("svc", 1, "RESTART", "old", "cfg", "intent")
    k2 = idempotency_key("svc", 1, "RESTART", "old", "cfg", "intent")
    assert k1 == k2
    assert len(k1) == 32


def test_key_different_intent():
    k1 = idempotency_key("svc", 1, "RESTART", "old", "cfg", "intent-a")
    k2 = idempotency_key("svc", 1, "RESTART", "old", "cfg", "intent-b")
    assert k1 != k2


def test_prior_none():
    d = tempfile.mkdtemp()
    store = DurableIdempotencyStore(d)
    assert store.prior("key1") is None


def test_commit_and_check():
    d = tempfile.mkdtemp()
    store = DurableIdempotencyStore(d)
    k = idempotency_key("svc", 1, "RESTART", "old", "cfg", "intent")
    assert store.is_committed(k) is False
    store.commit(k, "COMMITTED", 100.0)
    assert store.is_committed(k) is True
    prior = store.prior(k)
    assert prior is not None
    assert prior["outcome"] == "COMMITTED"


def test_replay_does_not_commit_again():
    d = tempfile.mkdtemp()
    store = DurableIdempotencyStore(d)
    k = "replay-key"
    store.commit(k, "COMMITTED", 100.0)
    # second commit overwrites but is_committed still True
    assert store.is_committed(k) is True
