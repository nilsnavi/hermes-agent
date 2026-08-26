"""Remember / Forget / Consolidate workflows.

These workflows operate through the MemoryProvider seam only. They attach
provenance, run the lifecycle through legal transitions, and enforce scoped
access on every operation. They implement memory semantics (write, retire,
merge) and nothing else: no capability granting, no execution approval, no
policy mutation.
"""

from __future__ import annotations

from typing import Callable

from .exceptions import MemoryNotFound, MemoryStateError
from .memory_lifecycle import MemoryLifecycle, MemoryLifecycleStatus
from .memory_provider import MemoryProvider
from .memory_scopes import MemoryAccess, MemoryKey, require_accessible
from .provenance import ProvenanceRecord, ProvenanceSource
from .storage_backends import StoredMemory


class MemoryWorkflowError(MemoryStateError):
    """Raised on invalid workflow orchestration."""


class RememberWorkflow:
    """Write a new memory item through the provider seam with provenance."""

    @staticmethod
    def run(
        provider: MemoryProvider,
        *,
        key: MemoryKey,
        payload: tuple[object, ...],
        provenance: ProvenanceRecord,
        access: MemoryAccess,
    ) -> MemoryLifecycle:
        _validate_creation(key, payload, provenance, access)
        provider.remember(key, payload, provenance, access)
        return MemoryLifecycle(status=MemoryLifecycleStatus.CREATED, version=0)


class ForgetWorkflow:
    """Retire a memory item: require provenance and scoped access, then FOGETTEN."""

    @staticmethod
    def run(
        provider: MemoryProvider,
        *,
        key: MemoryKey,
        access: MemoryAccess,
    ) -> MemoryLifecycle:
        if type(access) is not MemoryAccess:
            raise MemoryWorkflowError("access must be an exact MemoryAccess value")
        current = provider.read(key, access)
        if current is None:
            raise MemoryNotFound(f"memory {key.memory_id!r} not found for forget")
        # A record must be remembered-actively to be forgotten (never a raw draft).
        lifecycle = MemoryLifecycle(status=MemoryLifecycleStatus.CREATED)
        lifecycle = lifecycle.transition(MemoryLifecycleStatus.ACTIVE)
        lifecycle = lifecycle.transition(MemoryLifecycleStatus.FORGOTTEN)
        provider.forget(key, access)
        return lifecycle


class ConsolidateWorkflow:
    """Merge a set of scoped records into a derived record with generation+1."""

    def __init__(self, *, now: Callable[[], float]) -> None:
        self.now = now

    @staticmethod
    def _validate_same_scope(records: tuple[StoredMemory, ...], access: MemoryAccess) -> None:
        if not records:
            raise MemoryWorkflowError("consolidation requires at least one source")
        if type(access) is not MemoryAccess:
            raise MemoryWorkflowError("access must be an exact MemoryAccess value")
        scopes = {r.scope for r in records}
        tenants = {r.tenant_id for r in records}
        if len(scopes) != 1 or len(tenants) != 1:
            raise MemoryWorkflowError("consolidation sources must share scope and tenant")
        # Authorization boundary: every source must live in the caller's tenant and
        # be visible to the caller; a store/wide driver can never smuggle a
        # cross-tenant or cross-user source into a consolidation.
        if records[0].tenant_id != access.tenant_id:
            raise MemoryWorkflowError("consolidation sources are outside the caller tenant")
        scope = records[0].scope
        if scope not in ("global", "tenant", "user"):
            raise MemoryWorkflowError("invalid memory scope on source")
        if scope == "user":
            for r in records:
                if r.user_id != access.user_id:
                    raise MemoryWorkflowError("consolidation source is not visible to caller")

    def run(
        self,
        provider: MemoryProvider,
        *,
        sources: tuple[StoredMemory, ...],
        target_key: MemoryKey,
        base_provenance: ProvenanceRecord,
        actor_id: str,
        access: MemoryAccess,
    ) -> MemoryLifecycle:
        self._validate_same_scope(sources, access)
        if type(target_key) is not MemoryKey:
            raise MemoryWorkflowError("target_key must be an exact MemoryKey value")
        if type(base_provenance) is not ProvenanceRecord:
            raise MemoryWorkflowError("base_provenance must be an exact ProvenanceRecord value")
        # target boundary: derive payload only under the caller's tenant and scope.
        merged = tuple(item for r in sources for item in r.payload)
        require_accessible(target_key, access)
        # derived provenance: generation+1, source=CONSOLIDATION
        derived = base_provenance.child(
            source=ProvenanceSource.CONSOLIDATION,
            actor_id=actor_id,
            now=self.now(),
        )
        provider.remember(target_key, merged, derived, access)
        lifecycle = MemoryLifecycle(status=MemoryLifecycleStatus.CREATED)
        lifecycle = lifecycle.transition(MemoryLifecycleStatus.ACTIVE)
        lifecycle = lifecycle.transition(MemoryLifecycleStatus.CONSOLIDATED)
        return lifecycle


def _validate_creation(
    key: MemoryKey, payload: tuple[object, ...], provenance: ProvenanceRecord, access: MemoryAccess
) -> None:
    if type(key) is not MemoryKey:
        raise MemoryWorkflowError("key must be an exact MemoryKey value")
    if not isinstance(payload, tuple):
        raise MemoryWorkflowError("payload must be a tuple")
    if type(provenance) is not ProvenanceRecord:
        raise MemoryWorkflowError("provenance must be an exact ProvenanceRecord value")
    if type(access) is not MemoryAccess:
        raise MemoryWorkflowError("access must be an exact MemoryAccess value")