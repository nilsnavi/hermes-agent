"""Authentication boundaries.

The platform API derives the tenant/user scope from an authenticated principal,
never from a trustable request body. This module defines the principal contract
and a fail-closed boundary check: a request must present a valid bearer
principal, and any tenant claim in the body must match the authenticated
tenant or be rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet


class AuthenticationError(ValueError):
    """Raised on missing/invalid authentication or tenant mismatch."""


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated identity that scopes all API access."""

    tenant_id: str
    principal_id: str
    user_id: str = ""
    is_system: bool = False
    scopes: AbstractSet[str] = frozenset()

    def __post_init__(self) -> None:
        for name, value in (
            ("tenant_id", self.tenant_id),
            ("principal", self.principal_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise AuthenticationError(f"{name} must be a non-empty string")
        if self.user_id and not isinstance(self.user_id, str):
            raise AuthenticationError("user_id must be a string")
        if type(self.is_system) is not bool:
            raise AuthenticationError("is_system must be a bool")
        if not isinstance(self.scopes, AbstractSet) or isinstance(
            self.scopes, (str, bytes)
        ):
            raise AuthenticationError("scopes must be a set-like collection")
        for scope in self.scopes:
            if not isinstance(scope, str) or not scope.strip():
                raise AuthenticationError("scopes must be non-empty strings")
        object.__setattr__(self, "scopes", frozenset(self.scopes))

    def require_scope(self, scope: str) -> None:
        if not isinstance(scope, str) or not scope.strip():
            raise AuthenticationError("scope must be a non-empty string")
        if scope not in self.scopes:
            raise AuthenticationError(
                f"principal {self.tenant_id}/{self.principal_id} lacks scope {scope!r}"
            )


def authenticate_bearer(
    token: object,
    *,
    expected_token: str,
    tenant_id: str,
    principal_id: str,
    supported_scopes: AbstractSet[str],
    user_id: str = "",
) -> Principal:
    if not isinstance(token, str) or not token.strip():
        raise AuthenticationError("missing bearer token")
    if token != expected_token:
        raise AuthenticationError("invalid bearer token")
    if not isinstance(supported_scopes, AbstractSet) or isinstance(
        supported_scopes, (str, bytes)
    ):
        raise AuthenticationError("supported_scopes must be a set-like collection")
    # tenant_id and principal_id are supplied by the auth adapter that resolved
    # the token; the returned Principal is fully scoped and carries no trust in
    # any request body.
    return Principal(
        tenant_id=tenant_id,
        principal_id=principal_id,
        user_id=user_id,
        scopes=frozenset(supported_scopes),
    )


def enforce_tenant_boundary(principal: Principal, requested_tenant: object) -> str:
    """Reject a request whose body tenant does not match the principal.

    The principal is the source of truth. An empty/absent body tenant means the
    authenticated principal's tenant applies. A provided body tenant that
    differs from the principal's tenant is denied.
    """
    if type(principal) is not Principal:
        raise AuthenticationError("principal must be an exact Principal value")
    if not principal.tenant_id:
        raise AuthenticationError("principal has no tenant; access denied")
    if requested_tenant is None:
        return principal.tenant_id
    if not isinstance(requested_tenant, str) or not requested_tenant.strip():
        # Empty body tenant: the authenticated principal is the authority.
        return principal.tenant_id
    if requested_tenant != principal.tenant_id:
        raise AuthenticationError(
            f"requested tenant {requested_tenant!r} does not match authenticated "
            f"tenant {principal.tenant_id!r}"
        )
    return principal.tenant_id