"""Append-only audit model tests."""

import pytest

from agent.platform_persistence.audit import AuditLog, AuditRecord
from agent.platform_persistence.exceptions import AuditMutationForbidden
from agent.platform_persistence.isolation import TenantRef


def _record(entry_id: str = "e1", sequence: int = 0, tenant: str = "t1") -> AuditRecord:
    return AuditRecord(
        entry_id=entry_id,
        tenant=TenantRef(tenant),
        actor="system",
        action="task.created",
        occurred_at=1,
        payload_digest="abc123",
        sequence=sequence,
    )


def test_append_is_immutable_snapshot():
    log = AuditLog()
    log.append(_record(sequence=0))
    log.append(_record("e2", sequence=1))
    assert len(log) == 2
    # Re-append same entry id is refused (append-only).
    with pytest.raises(AuditMutationForbidden):
        log.append(_record(sequence=2))
    assert len(log) == 2


def test_sequence_must_be_contiguous():
    log = AuditLog()
    with pytest.raises(AuditMutationForbidden):
        log.append(_record(sequence=5))


def test_snapshot_is_ordered_by_sequence():
    log = AuditLog()
    log.append(_record("e1", sequence=0))
    log.append(_record("e2", sequence=1))
    log.append(_record("e3", sequence=2))
    snap = log.snapshot()
    assert [r.entry_id for r in snap] == ["e1", "e2", "e3"]


def test_log_has_no_mutation_operators():
    log = AuditLog()
    assert not hasattr(log, "update")
    assert not hasattr(log, "delete")
    assert not hasattr(log, "remove")


def test_record_requires_finite_fields():
    with pytest.raises(AuditMutationForbidden):
        AuditRecord(
            entry_id="", tenant=TenantRef("t1"), actor="s", action="a",
            occurred_at=0, payload_digest="d", sequence=0,
        )
    with pytest.raises(AuditMutationForbidden):
        AuditRecord(
            entry_id="e", tenant=TenantRef("t1"), actor="s", action="a",
            occurred_at=-1, payload_digest="d", sequence=0,
        )


def test_record_requires_exact_tenantref():
    bad_tenant = object()
    with pytest.raises(AuditMutationForbidden):
        AuditRecord(  # type: ignore[arg-type]
            entry_id="e", tenant=bad_tenant, actor="s", action="a",
            occurred_at=0, payload_digest="d", sequence=0,
        )