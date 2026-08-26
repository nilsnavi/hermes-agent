"""Deny-by-default policy engine.

The policy engine is a pure fail-closed decision function. It never performs
work; it only answers whether an operation is explicitly permitted for a given
scope. Absence of an explicit grant is a denial. There is no default grant,
no auto-approval, and no caller-supplied verdict: a granted permission is the
single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import AbstractSet

from .exceptions import DeniedOperation, InvalidPermission
from .permissions import CANONICAL_PERMISSIONS, PermissionGrant, PlatformScope


class PolicyDecision(Enum):
    PERMITTED = "permitted"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class PolicyVerdict:
    decision: PolicyDecision
    permission: str
    scope: PlatformScope
    reason: str


class DenyByDefaultPolicy:
    """Evaluates a single permission request against explicit grants.

    As a rule object it is stateless and thread-safe: it owns no grant store
    and cannot be mutated into a permissive configuration. Grants are supplied
    per call.
    """

    @staticmethod
    def evaluate(
        scope: PlatformScope,
        permission: str,
        *,
        grants: AbstractSet[PermissionGrant] = frozenset(),
    ) -> PolicyVerdict:
        if type(scope) is not PlatformScope:
            raise InvalidPermission("scope must be an exact PlatformScope value")
        if permission not in CANONICAL_PERMISSIONS:
            raise InvalidPermission(f"unknown platform permission {permission!r}")

        effective_grants = [
            grant
            for grant in grants
            if type(grant) is PermissionGrant and grant.scope == scope
        ]
        granted = any(grant.has(permission) for grant in effective_grants)
        if granted:
            return PolicyVerdict(
                PolicyDecision.PERMITTED, permission, scope, "explicit grant"
            )
        return PolicyVerdict(
            PolicyDecision.DENIED,
            permission,
            scope,
            "no explicit grant (deny by default)",
        )

    @staticmethod
    def require(
        scope: PlatformScope,
        permission: str,
        *,
        grants: AbstractSet[PermissionGrant] = frozenset(),
    ) -> None:
        verdict = DenyByDefaultPolicy.evaluate(
            scope, permission, grants=frozenset(grants)
        )
        if verdict.decision is not PolicyDecision.PERMITTED:
            raise DeniedOperation(
                f"operation {permission!r} denied for scope "
                f"{scope.tenant_id}/{scope.principal}: {verdict.reason}"
            )

    @staticmethod
    def permitted_permissions(
        scope: PlatformScope,
        grants: AbstractSet[PermissionGrant] = frozenset(),
    ) -> frozenset[str]:
        effective_grants = [
            grant
            for grant in grants
            if type(grant) is PermissionGrant and grant.scope == scope
        ]
        return frozenset(
            permission
            for permission in sorted(CANONICAL_PERMISSIONS)
            if any(grant.has(permission) for grant in effective_grants)
        )