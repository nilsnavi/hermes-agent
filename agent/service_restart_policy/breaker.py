"""Durable per-service failure circuit breaker."""
from __future__ import annotations

from ._durable import DurableStateCorrupt, JsonTransaction, require_finite_time


class DurableCircuitBreaker:
    def __init__(self, root, threshold: int, cooldown: float) -> None:
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
            raise ValueError("breaker threshold must be a positive integer")
        self.threshold = threshold
        self.cooldown = require_finite_time(cooldown)
        if self.cooldown <= 0:
            raise ValueError("breaker cooldown must be positive")
        self._tx = JsonTransaction(root, "circuit-breakers")

    def allow(self, service_id: str, now: float) -> bool:
        now = require_finite_time(now)
        def change(data):
            rec = data.get(service_id, {})
            if not isinstance(rec, dict):
                raise DurableStateCorrupt("invalid breaker record")
            opened = rec.get("opened_at")
            if opened is not None:
                try:
                    opened = require_finite_time(opened)
                except ValueError as exc:
                    raise DurableStateCorrupt("invalid breaker timestamp") from exc
            if opened is not None and now - opened >= self.cooldown:
                data[service_id] = {"failures": 0}
                return True
            return opened is None
        return self._tx.update(change)

    def record_failure(self, service_id: str, now: float) -> None:
        now = require_finite_time(now)
        def change(data):
            rec = data.setdefault(service_id, {"failures": 0})
            if not isinstance(rec, dict):
                raise DurableStateCorrupt("invalid breaker record")
            rec["failures"] = int(rec.get("failures", 0)) + 1
            if rec["failures"] >= self.threshold:
                rec["opened_at"] = now
        self._tx.update(change)

    def record_success(self, service_id: str) -> None:
        self._tx.update(lambda data: data.update({service_id: {"failures": 0}}))


class RestartCircuitBreaker(DurableCircuitBreaker):
    """Named Sprint 1.3.14 per-service restart circuit breaker."""


__all__ = ["DurableCircuitBreaker", "RestartCircuitBreaker"]
