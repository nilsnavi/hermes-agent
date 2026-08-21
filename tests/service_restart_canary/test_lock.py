"""Test durable per-service lock: single writer, stale recovery."""
import tempfile, time
from agent.service_restart_canary.lock import DurableServiceLock


def test_acquire():
    d = tempfile.mkdtemp()
    lk = DurableServiceLock(d, "svc", ttl=30)
    assert lk.acquire(100, "si", "nonce1", now=1000.0) is True


def test_second_writer_denied():
    d = tempfile.mkdtemp()
    lk = DurableServiceLock(d, "svc", ttl=30)
    lk.acquire(100, "si", "n1", now=1000.0)
    assert lk.acquire(200, "si2", "n2", now=1001.0) is False


def test_release():
    d = tempfile.mkdtemp()
    lk = DurableServiceLock(d, "svc", ttl=30)
    lk.acquire(100, "si", "n1", now=1000.0)
    assert lk.release(100, "n1") is True
    assert lk.acquire(300, "si3", "n3", now=1010.0) is True  # freed


def test_release_wrong_owner():
    d = tempfile.mkdtemp()
    lk = DurableServiceLock(d, "svc", ttl=30)
    lk.acquire(100, "si", "n1", now=1000.0)
    assert lk.release(999, "n1") is False  # wrong pid


def test_stale_expired():
    d = tempfile.mkdtemp()
    lk = DurableServiceLock(d, "svc", ttl=5)
    lk.acquire(100, "si", "n1", now=1000.0)
    # after ttl
    assert lk.acquire(200, "si2", "n2", now=2000.0) is True  # stale ok
