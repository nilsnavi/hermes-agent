"""Unified Memory Gateway.

The single entry point for memory operations in the platform. The gateway wraps
a MemoryProvider seam and the retrieval pipeline, exposing remember/forget/
consolidate/retrieve. It is DATA-only: it never grants capability, never
approves execution, never mutates policy, and never bypasses SystemBoundary.
It binds every operation to an explicit MemoryAccess so cross-tenant/cross-user
is impossible by construction.
"""

from __future__ import annotations

from typing import Callable

from .exceptions import MemoryScopeError
from .memory_lifecycle import MemoryLifecycle
from .memory_provider import MemoryProvider
from .memory_scopes import MemoryAccess, MemoryKey
from .memory_workflows import ConsolidateWorkflow, ForgetWorkflow, RememberWorkflow
from .provenance import ProvenanceRecord
from .retrieval import CandidateSource, ContextItem, RetrievalPipeline
from .storage_backends import StoredMemory


class UnifiedMemoryGateway:
    """Data-plane facade over provider + retrieval. No authority surface."""

    def __init__(
        self,
        provider: MemoryProvider,
        retrieval: RetrievalPipeline,
        *,
        now: Callable[[], float],
    ) -> None:
        self.provider = provider
        self.retrieval = retrieval
        self.consolidate_flow = ConsolidateWorkflow(now=now)
        self.remember_flow = RememberWorkflow()
        self.forget_flow = ForgetWorkflow()

    def remember(
        self,
        *,
        key: MemoryKey,
        payload: tuple[object, ...],
        provenance: ProvenanceRecord,
        access: MemoryAccess,
    ) -> MemoryLifecycle:
        return self.remember_flow.run(
            self.provider, key=key, payload=payload, provenance=provenance, access=access
        )

    def forget(
        self, *, key: MemoryKey, access: MemoryAccess
    ) -> MemoryLifecycle:
        return self.forget_flow.run(self.provider, key=key, access=access)

    def consolidate(
        self,
        *,
        sources: tuple[StoredMemory, ...],
        target_key: MemoryKey,
        base_provenance: ProvenanceRecord,
        actor_id: str,
        access: MemoryAccess,
    ) -> MemoryLifecycle:
        return self.consolidate_flow.run(
            self.provider,
            sources=sources,
            target_key=target_key,
            base_provenance=base_provenance,
            actor_id=actor_id,
            access=access,
        )

    def retrieve(
        self, *, access: MemoryAccess, query_text: str, top_k: int = 8
    ) -> tuple[ContextItem, ...]:
        if type(access) is not MemoryAccess:
            raise MemoryScopeError("access must be an exact MemoryAccess value")
        return self.retrieval.retrieve(access=access, query_text=query_text, top_k=top_k)

    @property
    def is_authority(self) -> bool:
        """Memory is DATA, never AUTHORITY."""
        return False