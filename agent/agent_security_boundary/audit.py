"""Execution audit linkage.

Every capability request produces an immutable, append-only audit record
carrying the full decision chain (agent/tenant/user/task/step/run/capability,
policy + boundary + executor dispositions, side-effect class, receipt id,
timestamp/provenance). An audit event is DATA, never a grant: recording a
decision does not authorise anything, and no audit row can retroactively change
a decision. The trail has no update/delete surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .exceptions import SecurityBoundaryError
from .status import AdmissionOutcome, Disposition, SideEffectClass

_Callable = Callable[[], float]


@dataclass(frozen=True, slots=True)
class ExecutionAuditRecord:
    """One immutable decision record emitted for one capability request."""

    sequence: int
    agent_id: str
    tenant_id: str
    user_id: str
    capability_requested: str
    side_effect_class: SideEffectClass
    policy_decision: str
    boundary_decision: str
    executor_disposition: str
    admission_outcome: AdmissionOutcome
    disposition: Disposition
    reason: str
    receipt_id: str | None
    task_id: str
    task_step_id: str
    agent_run_id: str
    timestamp: float

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "task_id": self.task_id,
            "task_step_id": self.task_step_id,
            "agent_run_id": self.agent_run_id,
            "capability_requested": self.capability_requested,
            "side_effect_class": self.side_effect_class.value,
            "policy_decision": self.policy_decision,
            "boundary_decision": self.boundary_decision,
            "executor_disposition": self.executor_disposition,
            "admission_outcome": self.admission_outcome.value,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "timestamp": self.timestamp,
        }


class AuditTrail:
    """Append-only sequence of immutable decision records."""

    __slots__ = ("_records", "_clock")

    def __init__(self, *, clock: _Callable | None = None) -> None:
        from time import time

        self._clock = clock if clock is not None else time
        self._records: list[ExecutionAuditRecord] = []

    def append(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        user_id: str,
        capability_requested: str,
        side_effect_class: SideEffectClass,
        policy_decision: str,
        boundary_decision: str,
        executor_disposition: str,
        admission_outcome: AdmissionOutcome,
        disposition: Disposition,
        reason: str,
        receipt_id: str | None,
        task_id: str = "",
        task_step_id: str = "",
        agent_run_id: str = "",
    ) -> ExecutionAuditRecord:
        record = ExecutionAuditRecord(
            sequence=len(self._records) + 1,
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            capability_requested=capability_requested,
            side_effect_class=side_effect_class,
            policy_decision=policy_decision,
            boundary_decision=boundary_decision,
            executor_disposition=executor_disposition,
            admission_outcome=admission_outcome,
            disposition=disposition,
            reason=reason,
            receipt_id=receipt_id,
            task_id=task_id,
            task_step_id=task_step_id,
            agent_run_id=agent_run_id,
            timestamp=self._clock(),
        )
        self._records.append(record)
        return record

    def snapshot(self) -> tuple[ExecutionAuditRecord, ...]:
        return tuple(self._records)

    def __len__(self) -> int:
        return len(self._records)


__all__ = ["AuditTrail", "ExecutionAuditRecord"]