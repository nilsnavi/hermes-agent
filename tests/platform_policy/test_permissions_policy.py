"""Deny-by-default policy engine tests."""

import pytest

from agent.platform_policy.exceptions import DeniedOperation, InvalidPermission
from agent.platform_policy.permissions import PermissionGrant, PlatformScope, intersect
from agent.platform_policy.policy import DenyByDefaultPolicy, PolicyDecision


def _scope(*, tenant_id: str = "ten-1", principal: str = "user-a",
           user_id: str = "u-1", is_system: bool = False) -> PlatformScope:
    return PlatformScope(
        tenant_id=tenant_id, principal=principal, user_id=user_id,
        is_system=is_system,
    )


def test_unknown_permission_is_invalid_at_construction():
    # Fail-closed: an unknown permission name can never be granted.
    with pytest.raises(InvalidPermission):
        PermissionGrant(_scope(), {"read_files", "agents.read"})


def test_default_grant_denies_everything():
    grant = PermissionGrant(_scope())
    for permission in ("agents.read", "tasks.submit", "memory.write"):
        assert not grant.has(permission)


def test_explicit_permission_is_granted():
    grant = PermissionGrant(_scope(), {"agents.read"})
    assert grant.has("agents.read")
    assert not grant.has("agents.register")


def test_deny_by_default_when_no_grant():
    verdict = DenyByDefaultPolicy.evaluate(_scope(), "tasks.submit")
    assert verdict.decision is PolicyDecision.DENIED
    assert "deny by default" in verdict.reason


def test_deny_when_grant_for_other_scope():
    scope = _scope()
    other = _scope(principal="user-b", user_id="u-2")
    grant = PermissionGrant(other, {"tasks.submit"})
    verdict = DenyByDefaultPolicy.evaluate(scope, "tasks.submit", grants={grant})
    assert verdict.decision is PolicyDecision.DENIED


def test_permit_when_exact_scope_granted():
    scope = _scope()
    grant = PermissionGrant(scope, {"tasks.submit"})
    verdict = DenyByDefaultPolicy.evaluate(scope, "tasks.submit", grants={grant})
    assert verdict.decision is PolicyDecision.PERMITTED


def test_require_raises_on_denied():
    with pytest.raises(DeniedOperation):
        DenyByDefaultPolicy.require(_scope(), "memory.delete")


def test_require_passes_on_granted():
    scope = _scope()
    grant = PermissionGrant(scope, {"memory.write"})
    DenyByDefaultPolicy.require(scope, "memory.write", grants={grant})


def test_unknown_permission_in_evaluate_rejected():
    with pytest.raises(InvalidPermission):
        DenyByDefaultPolicy.evaluate(_scope(), "read_files")


def test_tenant_is_required_for_scope():
    with pytest.raises(InvalidPermission):
        PlatformScope(tenant_id="", principal="p")


def test_scope_is_mutable_detail_but_value_verified():
    scope = _scope(tenant_id="   ten-2   ")
    assert scope.tenant_id == "ten-2"


def test_cross_tenant_grant_denied_even_if_principal_matches():
    scope_a = PlatformScope(tenant_id="ten-a", principal="p")
    scope_b = PlatformScope(tenant_id="ten-b", principal="p")
    grant = PermissionGrant(scope_b, {"audit.read"})
    verdict = DenyByDefaultPolicy.evaluate(scope_a, "audit.read", grants={grant})
    assert verdict.decision is PolicyDecision.DENIED


def test_intersection_requires_all_grants():
    scope = _scope()
    g1 = PermissionGrant(scope, {"agents.read", "agents.register"})
    g2 = PermissionGrant(scope, {"agents.read"})
    assert intersect(g1, g2) == frozenset({"agents.read"})


def test_intersection_across_scopes_rejected():
    g1 = PermissionGrant(_scope(tenant_id="t1"), {"agents.read"})
    g2 = PermissionGrant(_scope(tenant_id="t2"), {"agents.read"})
    with pytest.raises(InvalidPermission):
        intersect(g1, g2)


def test_permitted_permissions_returns_only_granted():
    scope = _scope()
    grant = PermissionGrant(scope, {"agents.read", "memory.read"})
    permitted = DenyByDefaultPolicy.permitted_permissions(scope, grants={grant})
    assert "agents.read" in permitted
    assert "tasks.submit" not in permitted


def test_empty_grants_yield_no_permitted_permissions():
    assert DenyByDefaultPolicy.permitted_permissions(_scope()) == frozenset()


def test_grant_is_immutable_snapshot():
    scope = _scope()
    mutable = {"agents.read"}
    grant = PermissionGrant(scope, mutable)
    mutable.add("agents.register")
    assert not grant.has("agents.register")