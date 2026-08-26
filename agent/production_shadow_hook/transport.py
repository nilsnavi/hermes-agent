"""Bounded, non-blocking shadow transport (Phase 8 §6, §14).

The production hook enqueues to a LOCAL bounded async queue (DATA ONLY; the
message never carries an executable object). ``try_enqueue`` never blocks and
returns ``False`` when the queue is full -> production drops shadow and continues.
No Redis/PostgreSQL ACK is ever awaited on the synchronous production path.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Protocol

from .envelope import ProductionShadowEnvelope


class ShadowTransport(Protocol):
    """Port for the bounded one-way transport (production -> shadow)."""

    def try_enqueue(self, envelope: ProductionShadowEnvelope) -> bool: ...

    def drain(self, limit: int) -> tuple[ProductionShadowEnvelope, ...]: ...

    def depth(self) -> int: ...


class InMemoryBoundedQueue:
    """Local bounded async queue; drop-on-full, never blocking."""

    __slots__ = ("_queue", "_max_depth", "_lock")

    def __init__(self, *, max_depth: int) -> None:
        if not isinstance(max_depth, int) or max_depth < 1:
            raise ValueError("max_depth must be a positive integer")
        self._max_depth = max_depth
        self._queue: deque[ProductionShadowEnvelope] = deque(maxlen=max_depth)
        self._lock = threading.Lock()

    def try_enqueue(self, envelope: ProductionShadowEnvelope) -> bool:
        """Non-blocking enqueue. False on full/unavailable (drop, no production impact)."""
        if type(envelope) is not ProductionShadowEnvelope:
            return False
        with self._lock:
            if len(self._queue) >= self._max_depth:
                return False
            self._queue.append(envelope)
            return True

    def drain(self, limit: int) -> tuple[ProductionShadowEnvelope, ...]:
        """Non-blocking bounded drain (FIFO), leaving the rest queued."""
        if not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        with self._lock:
            items = tuple(self._queue.popleft() for _ in range(min(limit, len(self._queue))))
            return items

    def depth(self) -> int:
        with self._lock:
            return len(self._queue)


__all__ = ["InMemoryBoundedQueue", "ShadowTransport"]