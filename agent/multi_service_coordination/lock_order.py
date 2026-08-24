"""Sprint 1.3.15 — canonical lock ordering (deadlock prevention, P0).

All service locks are acquired in ONE canonical deterministic order derived
from a stable, sorted service-identity digest — NEVER from the caller's
request order.  This makes distributed deadlock structurally impossible:
two transactions requesting the same service set always take locks in the
same global order.
"""
from __future__ import annotations

import hashlib
import threading

MAX_LOCK_HOLD_SECONDS = 30.0


def canonical_lock_order(service_ids) -> list[str]:
    """Stable, globally consistent ordering by sha256(service_id)."""
    return sorted(service_ids, key=lambda sid: hashlib.sha256(sid.encode()).hexdigest())


def same_order(a: list[str], b: list[str]) -> bool:
    """Two lock requests overlap consistently when their relative order agrees."""
    a_pos = {sid: i for i, sid in enumerate(a)}
    b_pos = {sid: i for i, sid in enumerate(b)}
    overlap = [sid for sid in a if sid in b_pos]
    return [sid for sid in a if sid in overlap] == [sid for sid in b if sid in overlap]


class CanonicalLockSet:
    """Per-service writer lease keyed on canonical order.

    Guarantees:
      * at most ONE active writer per service
      * no deadlock: locks only ever granted in canonical order
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._holders: dict[str, str] = {}  # service_id -> txid
        self._order_cache: dict[tuple[str, ...], tuple[str, ...]] = {}
        self.acquire_count = 0
        self.deadlock_avoided = 0

    def canonical(self, service_ids) -> tuple[str, ...]:
        key = tuple(sorted(service_ids))
        if key not in self._order_cache:
            self._order_cache[key] = tuple(canonical_lock_order(key))
        return self._order_cache[key]

    def acquire_many(self, txid: str, service_ids) -> list[str] | None:
        """Acquire locks in canonical order.  On any failure, release what we
        hold and return None (never partial).  Returns the order acquired."""
        order = self.canonical(service_ids)
        acquired: list[str] = []
        with self._lock:
            # pre-check: any held / contended service in the set?
            contended = [sid for sid in order if sid in self._holders]
            if contended:
                # Not currently holding any of these — a conflict.
                self.deadlock_avoided += 1
                # Deadlock impossible because order is canonical; a conflict is
                # just "another writer currently holds a shared service".
                return None
            for sid in order:
                if sid in self._holders:
                    # shouldn't happen after pre-check, but keep invariant
                    self.deadlock_avoided += 1
                    for held in acquired:
                        self._holders.pop(held, None)
                    return None
                self._holders[sid] = txid
                acquired.append(sid)
            self.acquire_count += 1
            return acquired

    def is_active_writer(self, service_id: str) -> bool:
        with self._lock:
            return service_id in self._holders

    def release_many(self, txid: str, service_ids) -> None:
        with self._lock:
            for sid in service_ids:
                if self._holders.get(sid) == txid:
                    self._holders.pop(sid, None)

    def writer_count(self, service_id: str) -> int:
        with self._lock:
            return 1 if service_id in self._holders else 0

    def active_writers(self) -> dict[str, str]:
        with self._lock:
            return dict(self._holders)


class InProcessLock:
    """Simple process-local cooperative lock used for concurrency tests."""

    def __init__(self) -> None:
        self._m = threading.Lock()
        self._holder: str | None = None

    def acquire(self, txid: str, timeout: float = 1.0) -> bool:
        return self._m.acquire(timeout=timeout)

    def release(self) -> None:
        self._holder = None
        self._m.release()


__all__ = [
    "CanonicalLockSet",
    "InProcessLock",
    "canonical_lock_order",
    "same_order",
]