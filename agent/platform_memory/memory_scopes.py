"""Memory scopes.

MemoryScope models the visibility boundary of a memory item. Items are always
written and read within an explicit tenant; a user-level scope further restricts
an item to a specific user. Retrieval computes permitted visibility: a caller
may only obtain items whose tenant matches the caller's tenant, and whose
user-scope (if any) matches the caller's user. Cross-tenant/cross-user access
is impossible by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .exceptions import MemoryScopeError


class MemoryScope(Enum):
    GLOBAL = "global"      # system-wide, never user-bound
    TENANT = "tenant"      # visible to the whole tenant
    USER = "user"          # visible to a single user within a tenant


@dataclass(frozen=True, slots=True)
class MemoryAccess:
    """Who is trying to access memory (tenant + optional user)."""

    tenant_id: str
    user_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise MemoryScopeError("tenant_id must be a non-empty string")
        if self.user_id is not None and not isinstance(self.user_id, str):
            raise MemoryScopeError("user_id must be a string or empty")
        object.__setattr__(self, "user_id", self.user_id or "")


@dataclass(frozen=True, slots=True)
class MemoryKey:
    """Immutable address of a memory item."""

    memory_id: str
    scope: MemoryScope
    tenant_id: str
    user_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.memory_id, str) or not self.memory_id.strip():
            raise MemoryScopeError("memory_id must be a non-empty string")
        if type(self.scope) is not MemoryScope:
            raise MemoryScopeError("scope must be an exact MemoryScope value")
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise MemoryScopeError("tenant_id must be a non-empty string")
        if self.scope is MemoryScope.USER and (not isinstance(self.user_id, str) or not self.user_id.strip()):
            raise MemoryScopeError("USER-scoped memory requires a non-empty user_id")
        if self.scope is not MemoryScope.USER:
            object.__setattr__(self, "user_id", self.user_id or "")

    def is_accessible_to(self, access: MemoryAccess) -> bool:
        if type(access) is not MemoryAccess:
            return False
        # cross-tenant: impossible
        if access.tenant_id != self.tenant_id:
            return False
        # USER-scoped: caller must be that same user (or a tenant operator with
        # authority — but operators are represented by an explicit user_id; we
        # enforce strict equality to prevent cross-user leakage).
        if self.scope is MemoryScope.USER:
            return access.user_id == self.user_id
        # GLOBAL always requires an explicit tenant match (scoped per-tenant).
        # TENANT- and GLOBAL-scoped items are visible to any member of the tenant.
        return access.tenant_id == self.tenant_id


def require_accessible(key: MemoryKey, access: MemoryAccess) -> None:
    """Raise MemoryScopeError if access cannot see key (fail-closed)."""
    if type(key) is not MemoryKey:
        raise MemoryScopeError("key must be an exact MemoryKey value")
    if not key.is_accessible_to(access):
        raise MemoryScopeError(
            f"memory {key.memory_id!r} is not accessible to tenant {access.tenant_id!r}"
        )