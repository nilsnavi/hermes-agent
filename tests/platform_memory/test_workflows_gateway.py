"""Remember/Forget/Consolidate workflows + gateway tests."""

import pytest

from agent.platform_memory.memory_gateway import UnifiedMemoryGateway
from agent.platform_memory.memory_lifecycle import MemoryLifecycleStatus
from agent.platform_memory.memory_scopes import MemoryAccess, MemoryKey, MemoryScope
from agent.platform_memory.memory_workflows import MemoryWorkflowError
from agent.platform_memory.provenance import ProvenanceRecord, ProvenanceSource
from agent.platform_memory.retrieval import RetrievalPipeline
from agent.platform_memory.storage_backends import MemoryQuery, StoredMemory
from agent.platform_memory.exceptions import MemoryNotFound


class InMemoryProvider:
    """Test double implementing MemoryProvider over an in-memory dict."""

    def __init__(self):
        self._store = {}

    def remember(self, key, payload, provenance, access):
        self._store[(key.tenant_id, key.memory_id)] = StoredMemory(
            key=key.memory_id, tenant_id=key.tenant_id, scope=key.scope.value,
            user_id=key.user_id, payload=payload,
            provenance_source=provenance.source.value, actor_id=provenance.actor_id,
            created_at=provenance.created_at, generation=provenance.generation,
        )

    def forget(self, key, access):
        self._store.pop((key.tenant_id, key.memory_id), None)

    def read(self, key, access):
        return self._store.get((key.tenant_id, key.memory_id))

    def candidates(self, query: MemoryQuery) -> tuple:
        return tuple(
            r for (tenant, _k), r in self._store.items() if tenant == query.tenant_id
        )


def _clock():
    return 1000.0


def _prov():
    return ProvenanceRecord(ProvenanceSource.USER, "u1", 1000.0, 0)


def _build():
    provider = InMemoryProvider()
    pipe = RetrievalPipeline(provider, now=_clock)
    gateway = UnifiedMemoryGateway(provider, pipe, now=_clock)
    return provider, pipe, gateway


def test_gateway_remember_then_retrieve():
    _provider, _pipe, gateway = _build()
    key = MemoryKey("m1", MemoryScope.TENANT, "t1")
    access = MemoryAccess("t1", "u1")
    lifecycle = gateway.remember(key=key, payload=("project", "alpha"), provenance=_prov(), access=access)
    assert lifecycle.status is MemoryLifecycleStatus.CREATED
    results = gateway.retrieve(access=access, query_text="project", top_k=4)
    assert any(item.key == "m1" for item in results)


def test_gateway_forget_removes():
    provider, _pipe, gateway = _build()
    key = MemoryKey("m1", MemoryScope.TENANT, "t1")
    access = MemoryAccess("t1", "u1")
    gateway.remember(key=key, payload=("x",), provenance=_prov(), access=access)
    lifecycle = gateway.forget(key=key, access=access)
    assert lifecycle.status is MemoryLifecycleStatus.FORGOTTEN
    assert provider.read(key, access) is None


def test_gateway_forget_missing_raises():
    _provider, _pipe, gateway = _build()
    key = MemoryKey("missing", MemoryScope.TENANT, "t1")
    with pytest.raises(MemoryNotFound):
        gateway.forget(key=key, access=MemoryAccess("t1", "u1"))


def test_gateway_consolidate_provenance_generation():
    _provider, _pipe, gateway = _build()
    access = MemoryAccess("t1", "u1")
    gateway.remember(key=MemoryKey("a", MemoryScope.TENANT, "t1"), payload=("part", "one"), provenance=_prov(), access=access)
    gateway.remember(key=MemoryKey("b", MemoryScope.TENANT, "t1"), payload=("part", "two"), provenance=_prov(), access=access)
    sources = (
        _provider.read(MemoryKey("a", MemoryScope.TENANT, "t1"), access),
        _provider.read(MemoryKey("b", MemoryScope.TENANT, "t1"), access),
    )
    lifecycle = gateway.consolidate(
        sources=tuple(s for s in sources if s),
        target_key=MemoryKey("merged", MemoryScope.TENANT, "t1"),
        base_provenance=_prov(), actor_id="agent1", access=access,
    )
    assert lifecycle.status is MemoryLifecycleStatus.CONSOLIDATED
    merged = _provider.read(MemoryKey("merged", MemoryScope.TENANT, "t1"), access)
    assert merged is not None
    assert merged.generation == 1
    assert merged.provenance_source == "consolidation"


def test_gateway_consolidate_rejects_mixed_scope():
    _provider, _pipe, gateway = _build()
    access = MemoryAccess("t1", "u1")
    a = StoredMemory("a", "t1", "tenant", "", ("x",), "user", "u1", 0.0, 0)
    b = StoredMemory("b", "t1", "user", "u2", ("y",), "user", "u1", 0.0, 0)
    with pytest.raises(MemoryWorkflowError):
        gateway.consolidate(
            sources=(a, b), target_key=MemoryKey("merged", MemoryScope.TENANT, "t1"),
            base_provenance=_prov(), actor_id="a1", access=access,
        )


def test_gateway_consolidate_rejects_cross_tenant_source():
    # Regression (BLOCKING-2): a source from another tenant (smuggled by a wide
    # driver) must never feed a consolidation under the caller's tenant.
    _provider, _pipe, gateway = _build()
    access = MemoryAccess("t1", "u1")
    cross = StoredMemory("c", "t2", "tenant", "", ("foreign",), "user", "x1", 0.0, 0)
    with pytest.raises(MemoryWorkflowError):
        gateway.consolidate(
            sources=(cross,), target_key=MemoryKey("merged", MemoryScope.TENANT, "t1"),
            base_provenance=_prov(), actor_id="a1", access=access,
        )


def test_gateway_consolidate_rejects_cross_user_source():
    _provider, _pipe, gateway = _build()
    access = MemoryAccess("t1", "u1")
    cross_user = StoredMemory("c", "t1", "user", "u2", ("hidden",), "user", "u2", 0.0, 0)
    with pytest.raises(MemoryWorkflowError):
        gateway.consolidate(
            sources=(cross_user,), target_key=MemoryKey("merged", MemoryScope.TENANT, "t1"),
            base_provenance=_prov(), actor_id="a1", access=access,
        )


def test_gateway_consolidate_rejects_cross_tenant_target():
    _provider, _pipe, gateway = _build()
    access = MemoryAccess("t1", "u1")
    src = StoredMemory("s", "t1", "tenant", "", ("x",), "user", "u1", 0.0, 0)
    with pytest.raises(Exception):
        # target in another tenant is not accessible to this caller
        gateway.consolidate(
            sources=(src,), target_key=MemoryKey("merged", MemoryScope.TENANT, "t2"),
            base_provenance=_prov(), actor_id="a1", access=access,
        )


def test_workflow_requires_key_and_access():
    _provider, _pipe, gateway = _build()
    key = MemoryKey("m1", MemoryScope.TENANT, "t1")
    with pytest.raises(MemoryWorkflowError):
        gateway.remember(key=key, payload=("x",), provenance=_prov(), access=object())  # type: ignore[arg-type]


def test_gateway_is_data_not_authority():
    _provider, _pipe, gateway = _build()
    assert gateway.is_authority is False
    assert not hasattr(gateway, "grant")
    assert not hasattr(gateway, "execute")
    assert not hasattr(gateway, "approve_execution")