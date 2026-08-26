"""Storage backends abstraction.

Defines the storage seams the memory platform writes through: a short-term
store (Redis), work/authority + long-term store (PostgreSQL), and a semantic
index (pgvector). These are pure Protocol seams — the concrete drivers live
behind them and are wired at deployment time. The control plane depends on the
seam, not on a driver, so it stays stdlib-only and never executes a tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class NoStorageBackend(RuntimeError):
    """Raised when a required backend seam is not wired."""


@dataclass(frozen=True, slots=True)
class StoredMemory:
    key: str
    tenant_id: str
    scope: str
    user_id: str
    payload: tuple[object, ...]
    provenance_source: str
    actor_id: str
    created_at: float
    generation: int


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    tenant_id: str
    scope: str
    user_id: str
    top_k: int = 8


class ShortTermStore(Protocol):
    """Redis seam — ephemeral, fast, TTL-driven."""

    def put(self, stored: StoredMemory, ttl_seconds: int) -> None: ...

    def get(self, key: str, tenant_id: str) -> StoredMemory | None: ...

    def delete(self, key: str, tenant_id: str) -> None: ...


class AuthorityWorkStore(Protocol):
    """PostgreSQL seam — authority/work memory, durable, tenant-scoped."""

    def write(self, stored: StoredMemory) -> None: ...

    def read(self, key: str, tenant_id: str) -> StoredMemory | None: ...

    def list(self, tenant_id: str, scope: str, user_id: str) -> tuple[StoredMemory, ...]: ...


class LongTermStore(Protocol):
    """PostgreSQL long-term memory seam — durable, consolidatable."""

    def write(self, stored: StoredMemory) -> None: ...

    def consolidate(self, key: str, tenant_id: str, consolidated: StoredMemory) -> None: ...

    def read(self, key: str, tenant_id: str) -> StoredMemory | None: ...


class SemanticIndex(Protocol):
    """pgvector seam — vector similarity search.

    The seam returns candidate keys by similarity; the retrieval pipeline still
    applies tenant/permission/redaction downstream. The index itself grants no
    authority over the retrieved payloads.
    """

    def search(self, query: MemoryQuery, embedding: tuple[float, ...]) -> tuple[str, ...]: ...

    def upsert(self, key: str, tenant_id: str, embedding: tuple[float, ...]) -> None: ...