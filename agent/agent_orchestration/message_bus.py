"""Message bus abstraction.

The bus delivers AgentMessage envelopes between agents. It is transport only:
it moves validated envelopes, enforces per-consumer isolation, rejects expired
messages, and deduplicates effective delivery. A bus MUST NOT execute tools,
inspect execution state, or grant any authority — it only routes data. All
message semantics that act on the world live downstream in the execution
kernel, never here.
"""

from __future__ import annotations

import threading
from typing import Callable, Protocol

from .messages import MessageEnvelope


class BusError(Exception):
    """Raised on malformed bus interaction."""


Consumer = Callable[[MessageEnvelope], None]


class MessageBus(Protocol):
    """Port for message transport (at-least-once, effective dedupe)."""

    def publish(self, envelope: MessageEnvelope) -> None: ...

    def consume_next(self, agent_id: str) -> MessageEnvelope | None: ...


class InMemoryMessageBus:
    """Thread-safe in-memory adapter implementing the MessageBus port.

    Each agent has an isolated inbox. ``consume_effective`` deduplicates on the
    (consumer, message_id) pair so a duplicate publish is not delivered twice
    as an effective action. Dead-letter-free: envelopes never carry execution
    intents here (they are data, not grants).
    """

    def __init__(self, *, now: Callable[[], float] | None = None) -> None:
        from time import time

        self._now = now or time
        self._inboxes: dict[str, list[MessageEnvelope]] = {}
        self._delivered: set[tuple[str, str]] = set()
        self._lock = threading.Lock()  # ORCH-002: atomic inspect->pop->mark

    def _inbox(self, agent_id: str) -> list[MessageEnvelope]:
        if agent_id not in self._inboxes:
            self._inboxes[agent_id] = []
        return self._inboxes[agent_id]

    def publish(self, envelope: MessageEnvelope) -> None:
        if type(envelope) is not MessageEnvelope:
            raise BusError("publish requires an exact MessageEnvelope value")
        if envelope.expires_at is not None and self._now() > envelope.expires_at:
            raise BusError("cannot publish an expired message")
        with self._lock:
            self._inbox(envelope.to_agent).append(envelope)

    def queued_count(self, agent_id: str) -> int:
        with self._lock:
            return len(self._inbox(agent_id))

    def consume_next(self, agent_id: str) -> MessageEnvelope | None:
        """Pop the next queued message under the bus lock (atomic)."""
        with self._lock:
            inbox = self._inbox(agent_id)
            if not inbox:
                return None
            return inbox.pop(0)

    def consume_effective(self, agent_id: str) -> MessageEnvelope | None:
        """ATOMIC effective consume: one thread delivers each envelope exactly once.

        The entire inspect->pop->mark sequence runs under the bus lock, so a
        duplicate envelope is never delivered twice even under heavy concurrency
        (delivery owner=1, duplicate processing=0).
        """
        with self._lock:
            while True:
                inbox = self._inbox(agent_id)
                if not inbox:
                    return None
                envelope = inbox.pop(0)
                if envelope.expires_at is not None and self._now() > envelope.expires_at:
                    continue
                key = (agent_id, envelope.message_id)
                if key in self._delivered:
                    continue
                self._delivered.add(key)
                return envelope

    def consume_atomic(self, agent_id: str) -> MessageEnvelope | None:
        """Alias for ``consume_effective`` (atomic inspect->pop->mark)."""
        return self.consume_effective(agent_id)

    def snapshot(self, agent_id: str) -> tuple[MessageEnvelope, ...]:
        with self._lock:
            return tuple(self._inbox(agent_id))

    def delivered_ids(self) -> frozenset[tuple[str, str]]:
        with self._lock:
            return frozenset(self._delivered)