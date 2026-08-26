"""Shared harness for Phase 8.3 worker tests.

Builds a real (read-only, control-plane) shadow ``ShadowDispatcher`` over the
Phase 6 read-only vertical, exactly mirroring the Phase 7 scenario harness, and
provides a tiny fake ``Runner`` for envelope/lifecycle unit tests that do not
need the vertical.
"""

from __future__ import annotations

import pytest

from agent.agent_integration.audit_store import InMemoryAuditStore
from agent.agent_integration.capabilities import ReadOnlyCapability
from agent.agent_integration.context import AgentContextAssembler
from agent.agent_integration.gate_token import RuntimeGrantSeal
from agent.agent_integration.metrics import MetricsRegistry
from agent.agent_integration.network_policy import NetworkReadOnlyPolicy
from agent.agent_integration.readonly_routing import ReadOnlyRouter
from agent.agent_integration.result import AgentObservation
from agent.agent_integration.vertical import (
    ReadOnlyAgentVertical,
    build_read_only_gate,
)
from agent.agent_integration.agent_run import AgentRunRegistry
from agent.agent_runtime.lifecycle import AgentLifecycleStatus
from agent.agent_system.runtime import SystemAgentRuntime
from agent.platform_memory.memory_scopes import MemoryAccess
from agent.platform_memory.retrieval import ContextItem
from agent.platform_shadow import (
    InMemoryClaimStore,
    ShadowAuditStore,
    ShadowBudget,
    ShadowMetrics,
    ShadowRuntime,
    ShadowSampler,
    ShadowSamplingMode,
    ShadowTracer,
)
from agent.platform_shadow.dispatcher import ShadowDispatcher


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        self.t += 0.001  # 1ms tick: stays inside heartbeat TTL
        return self.t


class SafeMemory:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def retrieve(self, *, access: MemoryAccess, query_text: str, top_k: int):
        self.requested.append(access.tenant_id)
        item = ContextItem(key="k", text=f"mem:{query_text}:{access.tenant_id}",
                           scope="*", similarity=0.9)
        return (item,) if top_k > 0 else ()


class Provider:
    def __init__(self, fail: Exception | None = None) -> None:
        self.reads = 0
        self.fail = fail

    def read(self, *, capability: ReadOnlyCapability, context):
        self.reads += 1
        if self.fail is not None:
            raise self.fail
        return AgentObservation(agent_run_id="run", agent_id="monitoring",
                                summary=f"observed {capability.value}", facts=("fact",),
                                confidence=0.9)


def _true_cap(kind: str) -> ReadOnlyCapability:
    return ReadOnlyCapability.READ_HEALTH


def build_vertical_runner(*, provider: Provider | None = None,
                          claim_healthy: bool = True) -> ShadowDispatcher:
    """Build a shadow dispatcher over the read-only vertical (no gateway)."""
    clock = _Clock()
    rt = SystemAgentRuntime(clock=clock)
    rt.register_system_agents()
    for a in ("planner", "research", "coding", "reviewer", "memory", "monitoring"):
        rt.transition(a, AgentLifecycleStatus.READY)
        rt.observe(a)

    gate = build_read_only_gate(registry=rt)
    router = ReadOnlyRouter(sealed_registry=rt, admission=rt.admission_status,
                            enabled={"planner", "research", "coding", "reviewer",
                                     "memory", "monitoring"})
    mem = SafeMemory()
    context = AgentContextAssembler(mem, registry_digest=rt.registry_digest())
    prov = provider if provider is not None else Provider()
    vertical = ReadOnlyAgentVertical(
        registry=rt, gate=gate, router=router, context=context,
        network_policy=NetworkReadOnlyPolicy(),
        seal=RuntimeGrantSeal(registry_digest=rt.registry_digest()),
        provider=prov, audit=InMemoryAuditStore(clock=clock),
        metrics=MetricsRegistry(), runs=AgentRunRegistry(), clock=clock,
    )
    runtime = ShadowRuntime(
        sampler=ShadowSampler(mode=ShadowSamplingMode.FULL_SHADOW),
        budget=ShadowBudget(max_concurrent=16, acquire_timeout_ms=5000),
        claims=InMemoryClaimStore(healthy=claim_healthy),
        vertical=vertical, audit=ShadowAuditStore(clock=clock),
        metrics=ShadowMetrics(), tracer=ShadowTracer(),
        clock=clock, capability_for=_true_cap,
        registry_digest=rt.registry_digest(), baseline_version="1.3.6",
    )
    return ShadowDispatcher(runtime)


@pytest.fixture
def vertical_runner():
    return build_vertical_runner()


@pytest.fixture
def vertical_runner_unhealthy_claims():
    return build_vertical_runner(claim_healthy=False)