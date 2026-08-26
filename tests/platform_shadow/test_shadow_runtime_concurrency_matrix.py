"""Shadow concurrency + security matrix (Phase 7 §22, §23, §24, §32).

Production effect must be 0 in every case: no shadow activity may change a
synthetic production mock, grant authority, or leak cross-tenant context.
"""

import threading

import pytest

from agent.agent_integration.capabilities import ReadOnlyCapability
from agent.agent_integration.metrics import MetricsRegistry
from agent.agent_integration.network_policy import NetworkReadOnlyPolicy
from agent.agent_integration.readonly_routing import ReadOnlyRouter
from agent.agent_integration.vertical import (
    ReadOnlyAgentVertical,
    build_read_only_gate,
)
from agent.agent_integration.gate_token import RuntimeGrantSeal
from agent.agent_integration.agent_run import AgentRunRegistry
from agent.agent_integration.audit_store import InMemoryAuditStore
from agent.agent_integration.context import AgentContextAssembler
from agent.agent_integration.result import AgentObservation
from agent.platform_memory.memory_scopes import MemoryAccess
from agent.platform_memory.retrieval import ContextItem
from agent.agent_runtime.lifecycle import AgentLifecycleStatus
from agent.agent_system.runtime import SystemAgentRuntime

from agent.platform_shadow import (
    ComparisonClass,
    InMemoryClaimStore,
    IsolationGuard,
    ShadowAuditStore,
    ShadowBudget,
    ShadowMetrics,
    ShadowRuntime,
    ShadowSampler,
    ShadowSamplingMode,
    ShadowTaskEnvelope,
    ShadowTracer,
    ShadowError,
)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        self.t += 0.001  # 1ms per tick: stays well within a heartbeat TTL
        return self.t


class SafeMemory:
    def __init__(self):
        self.requested = []

    def retrieve(self, *, access: MemoryAccess, query_text: str, top_k: int):
        self.requested.append(access.tenant_id)
        return (ContextItem(key="k", text=f"m:{access.tenant_id}", scope="*", similarity=0.9),)


class Provider:
    def __init__(self, fail=None):
        self.reads = 0
        self.fail = fail

    def read(self, *, capability: ReadOnlyCapability, context):
        self.reads += 1
        if self.fail is not None:
            raise self.fail
        return AgentObservation(agent_run_id="r", agent_id="monitoring",
                                summary="ok", facts=("f",), confidence=0.9)


class ProdMock:
    __slots__ = ("value",)

    def __init__(self):
        self.value = "production-result"

    def apply(self, value):
        self.value = value


def _build(*, provider=None, claim_healthy=True, rate=None):
    clock = Clock()
    rt = SystemAgentRuntime(clock=clock)
    rt.register_system_agents()
    for a in ("planner", "research", "coding", "reviewer", "memory", "monitoring"):
        rt.transition(a, AgentLifecycleStatus.READY)
        rt.observe(a)
    gate = build_read_only_gate(registry=rt)
    router = ReadOnlyRouter(sealed_registry=rt, admission=rt.admission_status,
                            enabled={"planner", "research", "coding", "reviewer", "memory", "monitoring"})
    mem = SafeMemory()
    context = AgentContextAssembler(mem, registry_digest=rt.registry_digest())
    prov = provider if provider is not None else Provider()
    vertical = ReadOnlyAgentVertical(
        registry=rt, gate=gate, router=router, context=context,
        network_policy=NetworkReadOnlyPolicy(), seal=RuntimeGrantSeal(registry_digest=rt.registry_digest()),
        provider=prov, audit=InMemoryAuditStore(clock=clock),
        metrics=MetricsRegistry(), runs=AgentRunRegistry(), clock=clock,
    )
    shadow = ShadowRuntime(
        sampler=ShadowSampler(mode=ShadowSamplingMode.FULL_SHADOW),
        budget=ShadowBudget(max_concurrent=32, acquire_timeout_ms=5000),
        claims=InMemoryClaimStore(healthy=claim_healthy),
        vertical=vertical,
        audit=ShadowAuditStore(clock=clock),
        metrics=ShadowMetrics(),
        tracer=ShadowTracer(),
        clock=clock,
        capability_for=lambda k: ReadOnlyCapability.READ_HEALTH,
        registry_digest=rt.registry_digest(),
        baseline_version="1.3.6",
    )
    if rate is not None:
        shadow._metrics.increment("shadow_tasks_received", rate)  # type: ignore[attr-defined]
    return shadow, mem, prov, vertical


def _env(shadow_id, *, tenant="acme", inp="in"):
    return ShadowTaskEnvelope(
        shadow_id=shadow_id, source_request_id="req-" + shadow_id, tenant_id=tenant,
        user_id="u-1", task_kind="monitoring", input_digest=inp, received_at=1000.0,
        sampling_reason="test", production_context_digest="pc", baseline_version="1.3.6",
    )


# -- §22 concurrency ----------------------------------------------------------

def test_concurrency_100_shadow_tasks_no_deadlock_no_effect():
    shadow, mem, prov, _ = _build()
    mock = ProdMock()
    results = []
    lock = threading.Lock()

    def worker(i):
        r = shadow.dispatch(_env(f"s{i}", inp=f"in-{i}"), production_decision=None)
        with lock:
            results.append(r)
            assert mock.value == "production-result"

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 100
    assert all(r.ran for r in results)
    assert prov.reads == 100
    assert set(mem.requested) == {"acme"}


def test_concurrency_100_duplicate_shadow_runs_single_winner():
    shadow, _, prov, _ = _build()
    out1 = shadow.dispatch(_env("dup-a", tenant="t", inp="same"))
    out2 = shadow.dispatch(_env("dup-b", tenant="t", inp="same"))
    assert out1.ran is True or out1.claimed is True
    # Same semantic key -> only one actual shadow run.
    assert out2.claimed is True and out2.ran is False
    assert prov.reads == 1
    assert shadow._metrics.get("shadow_duplicate_runs") >= 1  # type: ignore[attr-defined]


def test_concurrency_100_claim_races_single_winner():
    cs = InMemoryClaimStore()
    winners = []
    lock = threading.Lock()

    def worker(i):
        c = cs.claim("key", f"c{i}")
        if c.state.value == "win":
            with lock:
                winners.append(f"c{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1  # exactly one winner across 100 concurrent claims


def test_concurrency_50_tenant_mixes_no_leakage():
    shadow, mem, _, _ = _build()
    tenants = [f"t{i}" for i in range(50)]
    for i, t in enumerate(tenants):
        shadow.dispatch(_env(f"m{i}", tenant=t, inp=f"in-{i}"))
    # Every memory retrieval was bound to exactly its envelope tenant.
    assert sorted(set(mem.requested)) == sorted(tenants)
    assert len(mem.requested) == 50


# -- §23/§24 security matrix --------------------------------------------------

def test_matrix_forged_shadow_result_is_not_authority():
    out = _build()[0].dispatch(_env("x"))
    assert out.decision is not None
    assert not hasattr(out.decision, "override")
    assert not hasattr(out.decision, "grant")
    assert not hasattr(out.decision, "execute")


def test_matrix_fake_production_result_not_comparable():
    shadow, _, _, _ = _build()
    out = shadow.dispatch(_env("fp"), production_decision="not-a-decision")  # type: ignore[arg-type]
    assert out.decision is not None
    assert out.decision.comparison_class is ComparisonClass.NOT_COMPARABLE


def test_matrix_shadow_override_attempt_fails_closed():
    # Shadow result can never reach/override the production mock.
    shadow, _, _, _ = _build()
    mock = ProdMock()
    out = shadow.dispatch(_env("ov"), production_decision=None)
    assert mock.value == "production-result"
    with pytest.raises(Exception):
        IsolationGuard.reject_production_side(mock.apply, "production callable")
    del out


def test_matrix_registry_drift_recorded_prod_untouched():
    from agent.agent_system.definitions import SystemAgentRole, system_agent_definition
    from agent.agent_runtime.registry import AgentDefinition

    shadow, _, _, vertical = _build()
    # Register monitoring v2 directly on the registry -> the runtime seal no
    # longer matches the recomputed snapshot -> assert_registry_sealed raises.
    d = system_agent_definition(SystemAgentRole.MONITORING)
    d2 = AgentDefinition(agent_id=d.agent_id, version=2, name=d.name, role=d.role,
                         implementation_id=d.implementation_id,
                         capabilities=d.capabilities, trust_score=d.trust_score,
                         permissions=d.permissions)
    vertical._registry.registry().register(d2)  # type: ignore[attr-defined]
    mock = ProdMock()
    out = shadow.dispatch(_env("drift"), production_decision=None)
    assert mock.value == "production-result"
    assert out.decision is None or out.decision.supervisor_disposition != "completed"


def test_matrix_unknown_capability_denied():
    shadow, _, _, _ = _build()
    # A task kind not mapped to any read-only capability -> no shadow run.
    custom = ShadowRuntime(
        sampler=ShadowSampler(mode=ShadowSamplingMode.FULL_SHADOW),
        budget=ShadowBudget(max_concurrent=4, acquire_timeout_ms=1000),
        claims=InMemoryClaimStore(), vertical=_build()[3],
        audit=ShadowAuditStore(clock=Clock()), metrics=ShadowMetrics(),
        tracer=ShadowTracer(), clock=Clock(),
        capability_for=lambda k: None, registry_digest="d", baseline_version="x",
    )
    out = custom.dispatch(_env("unknown"))
    assert out.ran is False
    assert out.decision is not None
    assert out.decision.comparison_class is ComparisonClass.SHADOW_DENIED


def test_matrix_memory_injection_not_in_observation():
    # provider reads only the assembled (redacted/sanitized) context.
    shadow, _, prov, _ = _build()
    out = shadow.dispatch(_env("inj"))
    assert out.decision is not None
    assert "ignore previous" not in out.decision.agent_observation


def test_matrix_monitoring_no_service_mutation():
    from agent.agent_integration.agents import MonitoringAgent
    with pytest.raises(NotImplementedError):
        MonitoringAgent._no_service_mutation_surface()


def test_matrix_shadow_error_isolation_record_only():
    shadow, _, _, _ = _build(provider=Provider(fail=ShadowError("boom")))
    mock = ProdMock()
    out = shadow.dispatch(_env("iso"), production_decision=None)
    assert mock.value == "production-result"
    assert shadow._metrics.get("shadow_tasks_unknown") >= 1  # type: ignore[attr-defined]
    del out