"""Bounded persistent audit interface (Phase 6 §6).

Closes Phase 5 risk #2 (in-memory audit). ``PersistentAuditStore`` is the port
a durable backend can satisfy; ``InMemoryAuditStore`` is a deterministic,
append-only, BOUNDED test/prototype backend that keeps the integration chain
fully audited without requiring PostgreSQL in the control plane. An audit event
is DATA ONLY, never authority: recording a decision never authorizes anything
and never retroactively changes a decision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Protocol
from uuid import uuid4


class AuditError(Exception):
    """Raised on malformed audit interaction."""


class AuditStoreFull(AuditError):
    """Raised when the bounded audit backend is full (append only, never drop)."""


_Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class ExecutionAuditEvent:
    """One immutable, full-chain control-plane audit record (data only)."""

    sequence: int
    task_id: str
    task_step_id: str
    agent_run_id: str
    agent_id: str
    tenant_id: str
    user_id: str
    route_decision: str
    memory_context_digest: str
    capability_intent: str
    policy_decision: str
    boundary_disposition: str
    execution_observation: str
    supervisor_disposition: str
    provenance: str
    timestamp: float

    def __post_init__(self) -> None:
        for name in (
            "task_id", "task_step_id", "agent_run_id", "agent_id", "tenant_id",
            "user_id", "boundary_disposition", "supervisor_disposition",
        ):
            object.__setattr__(self, name, _req(name, getattr(self, name)))
        if (
            not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise AuditError("sequence must be a non-negative integer")
        if not isinstance(self.timestamp, (int, float)) or not math.isfinite(float(self.timestamp)):
            raise AuditError("timestamp must be a finite number")

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "task_id": self.task_id,
            "task_step_id": self.task_step_id,
            "agent_run_id": self.agent_run_id,
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "route_decision": self.route_decision,
            "memory_context_digest": self.memory_context_digest,
            "capability_intent": self.capability_intent,
            "policy_decision": self.policy_decision,
            "boundary_disposition": self.boundary_disposition,
            "execution_observation": self.execution_observation,
            "supervisor_disposition": self.supervisor_disposition,
            "provenance": self.provenance,
            "timestamp": self.timestamp,
        }


def _req(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuditError(f"{name} must be a non-empty string")
    return value


class PersistentAuditStore(Protocol):
    """Port for a durable audit backend."""

    def append(self, event: ExecutionAuditEvent) -> ExecutionAuditEvent: ...

    def snapshot(self) -> tuple[ExecutionAuditEvent, ...]: ...

    def count(self) -> int: ...


class InMemoryAuditStore:
    """Deterministic, append-only, bounded test/prototype backend."""

    __slots__ = ("_records", "_clock", "_max")

    def __init__(self, *, clock: _Clock | None = None, max_records: int = 10_000) -> None:
        from time import time

        if (
            isinstance(max_records, bool)
            or not isinstance(max_records, int)
            or max_records < 1
        ):
            raise AuditError("max_records must be a positive integer")
        self._clock = clock if clock is not None else time
        self._max = max_records
        self._records: list[ExecutionAuditEvent] = []

    def append(self, event: ExecutionAuditEvent) -> ExecutionAuditEvent:
        if type(event) is not ExecutionAuditEvent:
            raise AuditError("append requires an exact ExecutionAuditEvent value")
        if len(self._records) >= self._max:
            raise AuditStoreFull(
                f"audit store full at {self._max} records (append-only, no drop)"
            )
        self._records.append(event)
        return event

    def snapshot(self) -> tuple[ExecutionAuditEvent, ...]:
        return tuple(self._records)

    def count(self) -> int:
        return len(self._records)

    def __len__(self) -> int:
        return len(self._records)


def build_audit_event(
    *,
    task_id: str,
    task_step_id: str,
    agent_run_id: str,
    agent_id: str,
    tenant_id: str,
    user_id: str,
    route_decision: str,
    capability_intent: str,
    boundary_disposition: str,
    supervisor_disposition: str,
    policy_decision: str = "",
    memory_context_digest: str = "",
    execution_observation: str = "",
    provenance: str = "",
    sequence: int,
    timestamp: float,
) -> ExecutionAuditEvent:
    """Construct a canonical, bounded audit event (pure data)."""
    return ExecutionAuditEvent(
        sequence=sequence,
        task_id=_req("task_id", task_id),
        task_step_id=_req("task_step_id", task_step_id),
        agent_run_id=_req("agent_run_id", agent_run_id),
        agent_id=_req("agent_id", agent_id),
        tenant_id=_req("tenant_id", tenant_id),
        user_id=_req("user_id", user_id),
        route_decision=route_decision or "n/a",
        memory_context_digest=memory_context_digest or "n/a",
        capability_intent=capability_intent or "n/a",
        policy_decision=policy_decision or "n/a",
        boundary_disposition=_req("boundary_disposition", boundary_disposition),
        execution_observation=execution_observation or "n/a",
        supervisor_disposition=_req("supervisor_disposition", supervisor_disposition),
        provenance=provenance or "control-plane:v6",
        timestamp=timestamp,
    )


def new_run_provenance() -> str:
    return f"run-{uuid4().hex[:16]}"


__all__ = [
    "AuditError",
    "AuditStoreFull",
    "ExecutionAuditEvent",
    "InMemoryAuditStore",
    "PersistentAuditStore",
    "build_audit_event",
    "new_run_provenance",
]