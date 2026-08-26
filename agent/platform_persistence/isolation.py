"""Immutable tenant/user isolation model.

Every platform record belongs to exactly one tenant and (for user-owned data)
one user. The isolation boundary is enforced by the model: a query or mutation
must carry an owner that matches the record's tenant (and, when the record is
user-scoped, its user). There is no cross-tenant path.
"""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import (
    PlatformPersistenceError,
    TenantIsolationViolation,
)

_MAX_TEXT_LENGTH = 256


def _require_tenant_id(name: object, label: str = "tenant_id") -> str:
    if not isinstance(name, str) or not name.strip():
        raise TenantIsolationViolation(f"{label} must be a non-empty string")
    normalized = name.strip()
    if len(normalized) > _MAX_TEXT_LENGTH:
        raise TenantIsolationViolation(f"{label} exceeds {_MAX_TEXT_LENGTH} characters")
    return normalized


@dataclass(frozen=True, slots=True)
class TenantRef:
    """Identity of a tenant for a durable platform record."""

    tenant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _require_tenant_id(self.tenant_id))


@dataclass(frozen=True, slots=True)
class Owner:
    """The scoped identity allowed to access a record.

    A record owned by `Owner(tenant)` is tenant-scoped only; a record owned by
    `Owner(tenant, user)` is additionally user-scoped. Access by a different
    user, or by a different tenant, is a boundary violation.
    """

    tenant: TenantRef
    user_id: str = ""

    def __post_init__(self) -> None:
        if type(self.tenant) is not TenantRef:
            raise TenantIsolationViolation("tenant must be an exact TenantRef value")
        if self.user_id:
            if not isinstance(self.user_id, str) or not self.user_id.strip():
                raise TenantIsolationViolation("user_id must be a non-empty string")
            object.__setattr__(self, "user_id", self.user_id.strip())
        else:
            object.__setattr__(self, "user_id", "")

    @property
    def is_user_scoped(self) -> bool:
        return bool(self.user_id)

    def can_access(self, other: "Owner") -> bool:
        if type(other) is not Owner:
            raise PlatformPersistenceError("other must be an exact Owner value")
        if self.tenant != other.tenant:
            return False
        if not other.is_user_scoped:
            # Tenant-scoped target is readable by any actor within the tenant.
            return True
        if not self.is_user_scoped:
            # A tenant-scoped (system) actor may read a user-scoped target.
            return True
        return self.user_id == other.user_id

    def require_access(self, other: "Owner") -> None:
        if not self.can_access(other):
            target = f"{other.tenant.tenant_id}/{other.user_id or '*'}"
            actor = f"{self.tenant.tenant_id}/{self.user_id or '*'}"
            raise TenantIsolationViolation(
                f"owner {target} is not accessible to actor {actor}"
            )


def ensure_same_tenant(*owners: Owner) -> TenantRef:
    if not owners:
        raise TenantIsolationViolation("at least one owner is required")
    for owner in owners:
        if type(owner) is not Owner:
            raise PlatformPersistenceError("owner must be an exact Owner value")
    first = owners[0].tenant
    for owner in owners[1:]:
        if owner.tenant != first:
            raise TenantIsolationViolation(
                "all owners must belong to the same tenant"
            )
    return first