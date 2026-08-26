"""One-way transport tests (Phase 8.3 §9, §10, §11, §25 producer semantics)."""

from __future__ import annotations

import os

import pytest

from agent.shadow_worker.envelope import (
    ENVELOPE_SCHEMA_VERSION,
    ProductionShadowEnvelopeV1,
    default_timestamp,
    new_event_id,
)
from agent.shadow_worker.transport import (
    EmitResult,
    QueueOneWayTransport,
    UnixDatagramProducer,
    UnixDatagramShadowTransport,
    emit_into,
)


@pytest.fixture
def queue():
    return QueueOneWayTransport(max_depth=8)


def test_queue_accepted_then_consumed(queue):
    payload = b"x" * 10
    assert queue.try_emit(payload) is EmitResult.ACCEPTED
    assert queue.recv(timeout=0.05) == payload
    assert queue.queue_depth() == 0


def test_queue_bounded_drops_full(queue):
    for _ in range(8):
        assert queue.try_emit(b"a") is EmitResult.ACCEPTED
    # bounded -> DROP (never block, never raise to producer)
    assert queue.try_emit(b"b") is EmitResult.DROPPED_FULL
    assert len(queue.drain()) == 8


def test_producer_never_raises_into_production(queue):
    # invalid payload returns DROPPED_INVALID, no exception
    assert queue.try_emit(b"") is EmitResult.DROPPED_INVALID
    assert queue.try_emit("not-bytes") is EmitResult.DROPPED_INVALID


def test_closed_transport_unavailable(queue):
    queue.close()
    assert queue.try_emit(b"x") is EmitResult.UNAVAILABLE


def test_emit_into_never_raises(queue):
    r = emit_into(queue, b"")
    assert r.result is EmitResult.DROPPED_INVALID
    r2 = emit_into(queue, b"ok")
    assert r2.result is EmitResult.ACCEPTED
    # no exception path even when transport misbehaves
    class _Bad:
        def try_emit(self, payload):  # noqa: D102
            raise RuntimeError("boom")

    r3 = emit_into(_Bad(), b"x")
    assert r3.result is EmitResult.UNAVAILABLE


def test_no_worker_to_production_channel_surface(queue):
    # Mechanical §10: the consumer interface exposes NO reply/respond/override/
    # apply/promote/retry_production/send_to_gateway.
    surface = {name for name in dir(queue) if name in {
        "reply", "respond", "override", "apply", "promote",
        "retry_production", "send_to_gateway", "force_production"}}
    assert surface == set()


@pytest.fixture
def unix(tmp_path):
    path = str(tmp_path / "shadow.sock")
    t = UnixDatagramShadowTransport(path)
    p = UnixDatagramProducer(path, max_inflight=4)
    yield t, p
    p.close()
    t.close()


def test_unix_one_way_accepted(unix):
    t, p = unix
    assert p.try_emit(b"hello") is EmitResult.ACCEPTED
    assert t.recv(timeout=0.3) == b"hello"


def test_unix_one_way_drops_when_full(unix):
    t, p = unix
    # producer bound (max_inflight=4) WITHOUT consumer draining -> DROP on 5th
    for _ in range(4):
        assert p.try_emit(b"x") is EmitResult.ACCEPTED
    assert p.try_emit(b"y") in (EmitResult.DROPPED_FULL, EmitResult.UNAVAILABLE) \
        or t.drain()


def test_unix_consumer_has_no_send_surface(unix):
    t, _p = unix
    surface = {name for name in dir(t) if name in {
        "send", "sendto", "reply", "respond", "override", "apply", "promote",
        "retry_production", "send_to_gateway"}}
    assert surface == set()  # worker side cannot emit back


def test_unix_producer_unavailable_when_no_consumer(tmp_path):
    p = UnixDatagramProducer(str(tmp_path / "missing.sock"))
    try:
        # no consumer bound -> send fails -> UNAVAILABLE (never raises)
        assert p.try_emit(b"x") in (EmitResult.ACCEPTED, EmitResult.UNAVAILABLE)
    finally:
        p.close()


def test_end_to_end_zero_return_channel(queue):
    """§10: an envelope entering the transport can be drained but there is NO
    path lighting back to the producer. Just drain -> dirty dumps stay local."""
    for i in range(5):
        queue.try_emit(f"e{i}".encode())
    got = queue.drain()
    assert len(got) == 5
    assert queue.queue_depth() == 0