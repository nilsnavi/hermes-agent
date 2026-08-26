"""Canonical platform permission model and deny-by-default evaluation.

The permission model is the platform policy core. Every permission is denied
unless it is explicitly present in a grant owned by an authenticated scope.
There is no inheritance, no wildcard, and no negative-exception path: a request
is permitted only if the exact permission name is directly granted for the
exact principal+tenant scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet

from .exceptions import InvalidPermission

# Canonical permission vocabulary. Unknown names are invalid at construction
# time (fail-closed), so a caller can never smuggle an unrecognised name and
# have the evaluator treat it as granted-by-default.
CANONICAL_PERMISSIONS: frozenset[str] = frozenset(
    {
        # Agent admin surface
        "agents.read",
        "agents.register",
        "agents.disable",
        # Task submission and inspection
        "tasks.submit",
        "tasks.read",
        "tasks.cancel",
        # Memory surface
        "memory.read",
        "memory.write",
        "memory.delete",
        # Audit/observability
        "audit.read",
        # System-level (reserved; never granted to end principals in MVP)
        "system.operate",
    }
)

# Capability-permission mapping used by capability requests.
CAPABILITY_PERMISSION_ROLE: frozenset[str] = frozenset(
    {
        "planner",
        "research",
        "coding",
        "reviewer",
        "memory",
    }
)

_MAX_PERMISSIONS = 256


def _require_permission(name: object) -> None:
    if not isinstance(name, str) or name not in CANONICAL_PERMISSIONS:
        raise InvalidPermission(f"unknown platform permission {name!r}")


def _require_scope_name(name: object, label: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise InvalidPermission(f"{label} must be a non-empty string")
    normalized = name.strip()
    if len(normalized) > 256:
        raise InvalidPermission(f"{label} exceeds 256 characters")
    return normalized


@dataclass(frozen=True, slots=True)
class PlatformScope:
    """Identifies the authenticated principal and its tenant.

    ``user_id`` may be empty for a service/system principal, but the tenant is
    always required: a scope without a tenant cannot hold any permission.
    """

    tenant_id: str
    principal: str
    user_id: str = ""
    is_system: bool = False

    def __post_init__(self) -> None:
        tenant = _require_scope_name(self.tenant_id, "tenant_id")
        principal = _require_scope_name(self.principal, "principal")
        user_id = _require_scope_name(self.user_id, "user_id") if self.user_id else ""
        if type(self.is_system) is not bool:
            raise InvalidPermission("is_system must be a bool")
        object.__setattr__(self, "tenant_id", tenant)
        object.__setattr__(self, "principal", principal)
        object.__setattr__(self, "user_id", user_id)


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    """An explicit set of granted permissions for one scope.

    Immutable and copy-out safe: the grant only ever exposes a frozen snapshot
    of its held permission set.
    """

    scope: PlatformScope
    permissions: AbstractSet[str] = frozenset()

    def __post_init__(self) -> None:
        if type(self.scope) is not PlatformScope:
            raise InvalidPermission("scope must be an exact PlatformScope value")
        if not isinstance(self.permissions, AbstractSet) or isinstance(
            self.permissions, (str, bytes)
        ):
            raise InvalidPermission("permissions must be a set-like collection")
        if len(self.permissions) > _MAX_PERMISSIONS:
            raise InvalidPermission("permissions exceeds the 256-item limit")
        for permission in self.permissions:
            _require_permission(permission)
        object.__setattr__(self, "permissions", frozenset(self.permissions))

    def has(self, permission: str) -> bool:
        _require_permission(permission)
        return permission in self.permissions

    def allows_any(self, permissions: AbstractSet[str]) -> bool:
        for permission in permissions:
            _require_permission(permission)
        return bool(self.permissions & frozenset(permissions))


def intersect(*grants: PermissionGrant) -> frozenset[str]:
    """Intersection of permission sets across grants (all must hold)."""
    if not grants:
        return frozenset()
    scope = grants[0].scope
    for grant in grants:
        if grant.scope != scope:
            raise InvalidPermission("cannot intersect grants across different scopes")
    result: set[str] | None = None
    for grant in grants:
        names = grant.permissions
        result = set(names) if result is None else (result & set(names))
    assert result is not None
    return frozenset(result)