"""Tenant/user isolation model tests."""

import pytest

from agent.platform_persistence.exceptions import (
    PlatformPersistenceError,
    TenantIsolationViolation,
)
from agent.platform_persistence.isolation import Owner, TenantRef, ensure_same_tenant


def _owner(tenant: str, user: str = "") -> Owner:
    return Owner(TenantRef(tenant), user)


def test_tenant_ref_required():
    with pytest.raises(TenantIsolationViolation):
        TenantRef("   ")


def test_same_tenant_and_user_access():
    actor = _owner("t1", "u1")
    other = _owner("t1", "u1")
    assert actor.can_access(other)
    actor.require_access(other)


def test_cross_tenant_denied_even_same_user():
    actor = _owner("t1", "u1")
    other = _owner("t2", "u1")
    assert not actor.can_access(other)
    with pytest.raises(TenantIsolationViolation):
        actor.require_access(other)


def test_cross_user_same_tenant_between_user_scoped_records():
    actor = _owner("t1", "u1")
    other = _owner("t1", "u2")
    assert not actor.can_access(other)


def test_tenant_scoped_record_accessible_to_any_user_in_tenant():
    actor = _owner("t1", "u1")
    tenant_scoped = _owner("t1")  # no user -> tenant-scoped
    assert actor.can_access(tenant_scoped)
    assert tenant_scoped.can_access(actor)


def test_user_cannot_access_other_tenant_scoped_record_actor_side():
    actor = _owner("t1", "u1")
    tenant_scoped = _owner("t1", "u2")
    assert not tenant_scoped.can_access(actor)


def test_ensure_same_tenant_passes():
    assert ensure_same_tenant(_owner("t1", "u1"), _owner("t1", "u2")).tenant_id == "t1"


def test_ensure_same_tenant_raises_on_mixed():
    with pytest.raises(TenantIsolationViolation):
        ensure_same_tenant(_owner("t1"), _owner("t2"))


def test_owner_validates_nonempty_user():
    with pytest.raises(TenantIsolationViolation):
        _owner("t1", "  ")


def test_owner_rejects_non_tenantref():
    with pytest.raises(PlatformPersistenceError):
        ensure_same_tenant(_owner("t1"), object())  # type: ignore[arg-type]


def test_require_access_rejects_foreign_object():
    with pytest.raises(PlatformPersistenceError):
        _owner("t1").can_access(object())  # type: ignore[arg-type]