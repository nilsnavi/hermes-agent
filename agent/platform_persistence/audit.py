"""Append-only audit model.

Audit records are immutable once written: they can be read and appended to, but
never updated or deleted. The model enforces immutability at the value boundary
by exposing only a read-only snapshot and refusing mutation operators.
"""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import AuditMutationForbidden
from .isolation import TenantRef


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One append-only audit event bound to a tenant."""

    entry_id: str
    tenant: TenantRef
    actor: str
    action: str
    occurred_at: int
    payload_digest: str
    sequence: int

    def __post_init__(self) -> None:
        if type(self.tenant) is not TenantRef:
            raise AuditMutationForbidden("tenant must be an exact TenantRef value")
        for name in ("entry_id", "actor", "action", "payload_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise AuditMutationForbidden(f"{name} must be a non-empty string")
        for name in ("occurred_at", "sequence"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AuditMutationForbidden(f"{name} must be a non-negative integer")


class AuditLog:
    """In-memory append-only audit store for the platform.

    Production persistence is delegated to an executor; this class verifies the
    append-only contract and exposes an immutable snapshot. The log cannot be
    mutated: append and snapshot are the only operations.
    """

    __slots__ = ("_entries", "_sequence")

    def __init__(self) -> None:
        self._entries: dict[str, AuditRecord] = {}
        self._sequence = 0

    def append(self, record: AuditRecord) -> AuditRecord:
        if type(record) is not AuditRecord:
            raise AuditMutationForbidden("record must be an exact AuditRecord value")
        if record.entry_id in self._entries:
            raise AuditMutationForbidden(
                f"audit entry {record.entry_id!r} already exists (append-only)"
            )
        if record.sequence != self._sequence:
            raise AuditMutationForbidden("audit sequence must be contiguous")
        self._entries[record.entry_id] = record
        self._sequence += 1
        return record

    def get(self, entry_id: str) -> AuditRecord:
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise AuditMutationForbidden("entry_id must be a non-empty string")
        return self._entries[entry_id]

    def snapshot(self) -> tuple[AuditRecord, ...]:
        return tuple(
            self._entries[entry_id]
            for entry_id in sorted(self._entries, key=lambda key: self._entries[key].sequence)
        )

    def __len__(self) -> int:
        return len(self._entries)

    def _mutable_attribute(self) -> None:
        raise AuditMutationForbidden("audit log has no mutable attributes")