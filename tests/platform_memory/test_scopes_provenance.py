"""Memory scope and provenance tests."""

import pytest

from agent.platform_memory.memory_scopes import (
    MemoryAccess,
    MemoryKey,
    MemoryScope,
    require_accessible,
)
from agent.platform_memory.exceptions import MemoryScopeError
from agent.platform_memory.provenance import ProvenanceRecord, ProvenanceSource


def test_vendor_access():
    access = MemoryAccess(tenant_id="t1", user_id="u1")
    assert access.tenant_id == "t1"
    assert access.user_id == "u1"


def test_tenant_scoped_visible_to_any_member():
    key = MemoryKey("k1", MemoryScope.TENANT, "t1")
    assert key.is_accessible_to(MemoryAccess("t1", "u1"))
    assert key.is_accessible_to(MemoryAccess("t1", "u2"))


def test_user_scoped_visible_only_to_owner():
    key = MemoryKey("k1", MemoryScope.USER, "t1", user_id="u1")
    assert key.is_accessible_to(MemoryAccess("t1", "u1"))
    assert not key.is_accessible_to(MemoryAccess("t1", "u2"))


def test_cross_tenant_impossible():
    key = MemoryKey("k1", MemoryScope.TENANT, "t1")
    assert not key.is_accessible_to(MemoryAccess("t2", "u1"))


def test_require_accessible_fail_closed():
    key = MemoryKey("k1", MemoryScope.USER, "t1", user_id="u1")
    require_accessible(key, MemoryAccess("t1", "u1"))
    with pytest.raises(MemoryScopeError):
        require_accessible(key, MemoryAccess("t1", "u2"))


def test_user_scope_requires_user_id():
    with pytest.raises(MemoryScopeError):
        MemoryKey("k1", MemoryScope.USER, "t1", user_id="")  # type: ignore[arg-type]
    with pytest.raises(MemoryScopeError):
        MemoryKey("k1", MemoryScope.USER, "t1")


def test_provenance_requires_actor():
    with pytest.raises(Exception):
        ProvenanceRecord(ProvenanceSource.AGENT, "", 100.0, 0)


def test_provenance_child_increments_generation():
    origin = ProvenanceRecord(ProvenanceSource.USER, "u1", 100.0, 0)
    derived = origin.child(source=ProvenanceSource.CONSOLIDATION, actor_id="agent1", now=200.0)
    assert derived.generation == 1
    assert derived.source is ProvenanceSource.CONSOLIDATION