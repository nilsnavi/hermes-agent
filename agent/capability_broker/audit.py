"""Capability Broker audit contracts.

Phase 9.1.1 contains no filesystem audit sink. Production persistence is a
later wiring concern. Events intentionally exclude request arguments, secrets,
headers, raw responses, and raw exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .context import TrustedSurface


@dataclass(frozen=True, slots=True)
class CapabilityAuditEvent:
    request_id: str
    operation: str
    tenant_id: str
    principal_id: str
    surface: TrustedSurface
    decision: str
    result: str
    reason_code: str
    duration_ms: int

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise ValueError("duration_ms must not be negative")


class AuditSink(Protocol):
    def record(self, event: CapabilityAuditEvent) -> None:
        ...


class NullAuditSink:
    def record(self, event: CapabilityAuditEvent) -> None:
        if type(event) is not CapabilityAuditEvent:
            raise TypeError("event must be a CapabilityAuditEvent")


class InMemoryAuditSink:
    def __init__(self) -> None:
        self._events: list[CapabilityAuditEvent] = []

    @property
    def events(self) -> tuple[CapabilityAuditEvent, ...]:
        return tuple(self._events)

    def record(self, event: CapabilityAuditEvent) -> None:
        if type(event) is not CapabilityAuditEvent:
            raise TypeError("event must be a CapabilityAuditEvent")
        self._events.append(event)
