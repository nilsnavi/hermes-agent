"""MemoryProvider interface.

The single seam through which new memory integrates. The rest of the platform
(and any future memory source) talks to memory only through MemoryProvider; it
never reaches a store or backend directly. MemoryProvider is DATA boundary — it
reads and writes memory records, and it cannot grant capabilities, approve
execution, modify policies, or bypass SystemBoundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .memory_scopes import MemoryAccess, MemoryKey
from .provenance import ProvenanceRecord
from .storage_backends import StoredMemory


class MemoryProvider(Protocol):
    """Port for memory read/write. Provides no authority surface."""

    def remember(
        self,
        key: MemoryKey,
        payload: tuple[object, ...],
        provenance: ProvenanceRecord,
        access: MemoryAccess,
    ) -> None: ...

    def forget(self, key: MemoryKey, access: MemoryAccess) -> None: ...

    def read(self, key: MemoryKey, access: MemoryAccess) -> StoredMemory | None: ...


@dataclass(frozen=True, slots=True)
class MemoryProviderCoordinator:
    """Thin seam holder that binds the provider to its scoped access."""

    tenant_id: str
    user_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")

    def access(self) -> MemoryAccess:
        return MemoryAccess(tenant_id=self.tenant_id, user_id=self.user_id)