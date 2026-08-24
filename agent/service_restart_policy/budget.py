"""Durable rolling-hour per-service and global attempt/success budgets."""
from __future__ import annotations

from ._durable import DurableStateCorrupt, JsonTransaction, require_finite_time


class DurableHourlyBudgets:
    WINDOW = 3600.0

    def __init__(
        self,
        root,
        per_service_limit: int | None = None,
        global_limit: int | None = None,
        *,
        per_service_attempts: int = 2,
        per_service_successes: int = 1,
        global_attempts: int = 4,
        global_successes: int = 2,
    ) -> None:
        # Old two-limit construction remains a strict compatibility alias.
        if per_service_limit is not None:
            per_service_attempts = per_service_limit
            per_service_successes = per_service_limit
        if global_limit is not None:
            global_attempts = global_limit
            global_successes = global_limit
        limits = (per_service_attempts, per_service_successes, global_attempts, global_successes)
        if any(limit < 1 for limit in limits):
            raise ValueError("budget limits must be positive")
        self.per_service_attempts = per_service_attempts
        self.per_service_successes = per_service_successes
        self.global_attempts = global_attempts
        self.global_successes = global_successes
        self._tx = JsonTransaction(root, "hourly-budgets")

    def _events(self, data: dict, now: float) -> list[dict]:
        now = require_finite_time(now)
        cutoff = now - self.WINDOW
        raw_events = data.get("events", [])
        if not isinstance(raw_events, list):
            raise DurableStateCorrupt("budget events must be a list")
        events = []
        for event in raw_events:
            if not isinstance(event, dict) or not isinstance(event.get("service_id"), str):
                raise DurableStateCorrupt("invalid budget event")
            try:
                at = require_finite_time(event.get("at"))
            except ValueError as exc:
                raise DurableStateCorrupt("invalid budget event timestamp") from exc
            if event.get("kind") not in {"attempt", "success"}:
                raise DurableStateCorrupt("invalid budget event kind")
            if at > cutoff:
                events.append({**event, "at": at})
        return events

    @staticmethod
    def _count(events: list[dict], kind: str, service_id: str | None = None) -> int:
        return sum(
            e.get("kind") == kind and (service_id is None or e.get("service_id") == service_id)
            for e in events
        )

    def reserve_attempt(
        self, service_id: str, now: float, reservation_id: str | None = None
    ) -> bool:
        def change(data):
            events = self._events(data, now)
            if (
                self._count(events, "attempt", service_id) >= self.per_service_attempts
                or self._count(events, "attempt") >= self.global_attempts
                or not self._may_succeed(events, service_id)
            ):
                data["events"] = events
                return False
            events.append({
                "kind": "attempt", "service_id": service_id, "at": now,
                "reservation_id": reservation_id,
            })
            data["events"] = events
            return True

        return self._tx.update(change)

    def _may_succeed(self, events: list[dict], service_id: str) -> bool:
        return (
            self._count(events, "success", service_id) < self.per_service_successes
            and self._count(events, "success") < self.global_successes
        )

    def may_succeed(self, service_id: str, now: float) -> bool:
        events = self._events(self._tx.read(), now)
        return self._may_succeed(events, service_id)

    def owns_reservation(self, service_id: str, reservation_id: str, now: float) -> bool:
        events = self._events(self._tx.read(), now)
        return any(
            event.get("kind") == "attempt"
            and event.get("service_id") == service_id
            and event.get("reservation_id") == reservation_id
            for event in events
        )

    def record_success(
        self, service_id: str, now: float, reservation_id: str | None = None
    ) -> bool:
        def change(data):
            events = self._events(data, now)
            if not self._may_succeed(events, service_id):
                data["events"] = events
                return False
            if reservation_id is not None and not any(
                event.get("kind") == "attempt"
                and event.get("service_id") == service_id
                and event.get("reservation_id") == reservation_id
                for event in events
            ):
                return False
            events.append({
                "kind": "success", "service_id": service_id, "at": now,
                "reservation_id": reservation_id,
            })
            data["events"] = events
            return True

        return self._tx.update(change)

    def snapshot(self, service_id: str, now: float) -> dict[str, int]:
        events = self._events(self._tx.read(), now)
        return {
            "service_attempts": self._count(events, "attempt", service_id),
            "service_successes": self._count(events, "success", service_id),
            "global_attempts": self._count(events, "attempt"),
            "global_successes": self._count(events, "success"),
        }

    # Compatibility: one consume represents one successful operation.
    def consume(self, service_id: str, now: float) -> bool:
        if not self.reserve_attempt(service_id, now):
            return False
        return self.record_success(service_id, now)

    def counts(self, service_id: str, now: float) -> tuple[int, int]:
        snapshot = self.snapshot(service_id, now)
        return snapshot["service_attempts"], snapshot["global_attempts"]


class RestartBudget(DurableHourlyBudgets):
    """Named Sprint 1.3.14 per-service/global restart budget policy."""


__all__ = ["DurableHourlyBudgets", "RestartBudget"]
