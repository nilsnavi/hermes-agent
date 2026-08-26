"""Message bus abstraction tests."""

import pytest

from agent.agent_orchestration.message_bus import BusError, InMemoryMessageBus
from agent.agent_orchestration.messages import (
    MessageEnvelope,
    MessagePriority,
    MessageType,
)


def _env(message_id="m1", to_agent="research", expires_at=None) -> MessageEnvelope:
    return MessageEnvelope(
        message_id=message_id,
        schema_version=1,
        from_agent="planner",
        to_agent=to_agent,
        type=MessageType.REQUEST,
        priority=MessagePriority.NORMAL,
        task_id="t1",
        idempotency_key="idem-" + message_id,
        payload=("step", "s1"),
        expires_at=expires_at,
    )


class _Clock:
    def __init__(self, value: float = 1000.0) -> None:
        self._value = value

    def __call__(self) -> float:
        return self._value

    def set(self, value: float) -> None:
        self._value = value


def _bus(now: float = 1000.0):
    clock = _Clock(now)
    return InMemoryMessageBus(now=clock), clock


def test_publish_queues_for_consumer():
    bus = InMemoryMessageBus()
    bus.publish(_env(message_id="a", to_agent="research"))
    assert bus.queued_count("research") == 1
    assert bus.queued_count("coding") == 0


def test_consume_next_pop():
    bus = InMemoryMessageBus()
    bus.publish(_env(message_id="a", to_agent="research"))
    bus.publish(_env(message_id="b", to_agent="research"))
    first = bus.consume_next("research")
    assert first is not None and first.message_id == "a"
    assert bus.queued_count("research") == 1


def test_consume_effective_deduplicates():
    bus = InMemoryMessageBus()
    bus.publish(_env(message_id="a", to_agent="research"))
    first = bus.consume_effective("research")
    assert first is not None and first.message_id == "a"
    # Second identical delivery is deduplicated (no effective action twice).
    bus.publish(_env(message_id="a", to_agent="research"))
    assert bus.consume_effective("research") is None


def test_consumer_isolation():
    bus = InMemoryMessageBus()
    bus.publish(_env(message_id="a", to_agent="research"))
    assert bus.consume_effective("coding") is None
    assert bus.consume_effective("research") is not None


def test_expired_message_rejected_on_publish():
    bus, _ = _bus(now=200.0)
    with pytest.raises(BusError):
        bus.publish(_env(message_id="a", expires_at=100.0))


def test_expired_message_skipped_in_consume_effective():
    bus, clock = _bus(now=200.0)
    bus.publish(_env(message_id="live", expires_at=300.0))
    clock.set(350.0)
    bus.publish(_env(message_id="fresh", expires_at=500.0))
    result = bus.consume_effective("research")
    assert result is not None and result.message_id == "fresh"


def test_publish_rejects_non_envelope():
    bus = InMemoryMessageBus()
    with pytest.raises(BusError):
        bus.publish("not-an-envelope")  # type: ignore[arg-type]


def test_bus_carries_no_execution_authority():
    bus = InMemoryMessageBus()
    assert not hasattr(bus, "execute_tool")
    assert not hasattr(bus, "run")
    assert not hasattr(bus, "execute")
    assert not hasattr(bus, "authorize")
    assert not hasattr(bus, "grant")