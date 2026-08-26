"""Message hardening (Phase 6 §21, §22): atomic consume (ORCH-002) and
canonical payload (ORCH-001)."""

import io
import threading

import pytest

from agent.agent_orchestration.message_bus import InMemoryMessageBus
from agent.agent_orchestration.messages import (
    InvalidMessage,
    MessageEnvelope,
    MessagePriority,
    MessageType,
)


def _envelope(payload=(), *, message_id="m1", seed: int = 0):
    return MessageEnvelope(
        message_id=message_id or f"m{seed}",
        schema_version=1,
        from_agent="publisher",
        to_agent="consumer",
        type=MessageType.EVENT,
        priority=MessagePriority.NORMAL,
        task_id="task-1",
        idempotency_key=f"ik-{seed}",
        payload=payload,
    )


# -- ORCH-002 atomic consume --------------------------------------------------

def test_atomic_consume_each_message_delivered_exactly_once():
    n = 100
    bus = InMemoryMessageBus()
    for i in range(n):
        bus.publish(_envelope(message_id=f"m{i}", seed=i))

    delivered: list[str] = []
    lock = threading.Lock()

    def worker():
        while True:
            env = bus.consume_effective("consumer")
            if env is None:
                return
            with lock:
                delivered.append(env.message_id)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(delivered) == n  # every message delivered
    assert len(set(delivered)) == n  # no duplicates (delivery owner=1, dup=0)


def test_atomic_consume_duplicate_publish_not_delivered_twice():
    bus = InMemoryMessageBus()
    env = _envelope(message_id="dup")
    bus.publish(env)
    bus.publish(env)  # duplicate publish (same message_id)
    first = bus.consume_effective("consumer")
    assert first is not None and first.message_id == "dup"
    second = bus.consume_effective("consumer")
    # Duplicate is effective-delivered once only.
    assert not isinstance(second, MessageEnvelope) or second is None


def test_consume_atomic_alias_works():
    bus = InMemoryMessageBus()
    bus.publish(_envelope(message_id="x"))
    got = bus.consume_atomic("consumer")
    assert got is not None and got.message_id == "x"


# -- ORCH-001 canonical serializable payload ----------------------------------

def test_payload_allows_canonical_values():
    env = _envelope((1, 2.5, True, None, "ok", {"k": [1, 2]}))
    assert env.payload  # constructed fine


def test_payload_rejects_callable():
    with pytest.raises(InvalidMessage):
        _envelope((lambda: None,))


def test_payload_rejects_class():
    class _C:  # noqa: N801
        pass

    with pytest.raises(InvalidMessage):
        _envelope((_C,))


def test_payload_rejects_module():
    import sys

    with pytest.raises(InvalidMessage):
        _envelope((sys,))


def test_payload_rejects_file_handle():
    with pytest.raises(InvalidMessage):
        _envelope((io.StringIO("x"),))


def test_payload_rejects_arbitrary_object():
    with pytest.raises(InvalidMessage):
        _envelope((object(),))


def test_payload_rejects_non_finite_float():
    with pytest.raises(InvalidMessage):
        _envelope((float("nan"),))
    with pytest.raises(InvalidMessage):
        _envelope((float("inf"),))


def test_payload_rejects_too_deep_nesting():
    deep = (1, 2)
    for _ in range(8):
        deep = (deep,)
    with pytest.raises(InvalidMessage):
        _envelope(deep)


def test_payload_rejects_non_string_dict_keys():
    with pytest.raises(InvalidMessage):
        _envelope(({1: "x"},))