"""Standalone runner factory (Phase 8.3 §2 "independently executable").

Builds a ``ShadowDispatcher`` over the EXISTING Phase 7 read-only vertical so the
worker runs as its own process with a single read side.  This is the default an
Operator would wire to the real read-only vertical; tests inject their own.  It
imports NO gateway module, NO adapter, NO executor -- the worker stays decoupled
from the production gateway (``GATEWAY_RUNTIME_COUPLING=0``).

``build_standalone_worker_transport()`` returns an in-process bounded one-way
transport so ``python -m agent.shadow_worker.shadow_worker`` can be exercised
without any external network.
"""

from __future__ import annotations

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
    ShadowMetrics as RuntimeMetrics,
    ShadowRuntime,
    ShadowSampler,
    ShadowSamplingMode,
    ShadowTracer,
)
from agent.platform_shadow.dispatcher import ShadowDispatcher


class StandaloneProvider:
    """Dummy read-only provider for standalone/no-network execution (denied net)."""

    def read(self, *, capability: ReadOnlyCapability, context):  # type: ignore[no-untyped-def]
        return AgentObservation(
            agent_run_id="run",
            agent_id="monitoring",
            summary=f"observed {capability.value}",
            facts=("fact",),
            confidence=0.9,
        )


def build_standalone_runner() -> ShadowDispatcher:
    """Build a shadow dispatcher over the read-only vertical (no gateway)."""
    clock = _FixedClock()
    rt = SystemAgentRuntime(clock=clock)
    rt.register_system_agents()
    for a in ("planner", "research", "coding", "reviewer", "memory", "monitoring"):
        rt.transition(a, AgentLifecycleStatus.READY)
        rt.observe(a)

    gate = build_read_only_gate(registry=rt)
    router = ReadOnlyRouter(sealed_registry=rt, admission=rt.admission_status,
                            enabled={"planner", "research", "coding", "reviewer",
                                     "memory", "monitoring"})
    mem = _StandaloneMemory()
    context = AgentContextAssembler(mem, registry_digest=rt.registry_digest())
    vertical = ReadOnlyAgentVertical(
        registry=rt, gate=gate, router=router, context=context,
        network_policy=NetworkReadOnlyPolicy(), seal=RuntimeGrantSeal(registry_digest=rt.registry_digest()),
        provider=StandaloneProvider(), audit=InMemoryAuditStore(clock=clock),
        metrics=MetricsRegistry(), runs=AgentRunRegistry(), clock=clock,
    )
    runtime = ShadowRuntime(
        sampler=ShadowSampler(mode=ShadowSamplingMode.FULL_SHADOW),
        budget=ShadowBudget(max_concurrent=8, acquire_timeout_ms=2000),
        claims=InMemoryClaimStore(),
        vertical=vertical,
        audit=ShadowAuditStore(clock=clock),
        metrics=RuntimeMetrics(),
        tracer=ShadowTracer(),
        clock=clock,
        capability_for=_true_cap,
        registry_digest=rt.registry_digest(),
        baseline_version="1.3.6",
    )
    return ShadowDispatcher(runtime)


class _FixedClock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        self.t += 0.001  # 1ms tick keeps heartbeat inside TTL
        return self.t


class _StandaloneMemory:
    def retrieve(self, *, access: MemoryAccess, query_text: str, top_k: int):  # type: ignore[no-untyped-def]
        item = ContextItem(key="k", text=f"mem:{query_text}:{access.tenant_id}",
                           scope="*", similarity=0.9)
        return (item,) if top_k > 0 else ()


def _true_cap(kind: str) -> ReadOnlyCapability:
    return ReadOnlyCapability.READ_HEALTH


__all__ = ["StandaloneProvider", "build_standalone_runner"]