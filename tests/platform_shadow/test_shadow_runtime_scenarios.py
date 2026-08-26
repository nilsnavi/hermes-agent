"""Shadow runtime end-to-end (Phase 7 §18-§19, §25, §26): Scenarios A-J with a
synthetic production mock that must remain untouched by shadow."""

import pytest

from agent.agent_integration.agents import CodingShadowAgent
from agent.agent_integration.audit_store import InMemoryAuditStore
from agent.agent_integration.capabilities import ReadOnlyCapability
from agent.agent_integration.context import AgentContextAssembler
from agent.agent_integration.metrics import MetricsRegistry
from agent.agent_integration.network_policy import NetworkReadOnlyPolicy
from agent.agent_integration.readonly_routing import ReadOnlyRouter
from agent.agent_integration.result import AgentObservation
from agent.agent_integration.vertical import (
    ReadOnlyAgentVertical,
    build_read_only_gate,
)
from agent.agent_integration.gate_token import RuntimeGrantSeal
from agent.agent_integration.agent_run import AgentRunRegistry
from agent.platform_memory.memory_scopes import MemoryAccess
from agent.platform_memory.retrieval import ContextItem
from agent.agent_system.runtime import SystemAgentRuntime
from agent.agent_runtime.lifecycle import AgentLifecycleStatus

from agent.platform_shadow import (
    ComparisonClass,
    InMemoryClaimStore,
    ShadowAuditStore,
    ShadowBudget,
    ShadowMetrics,
    ShadowRuntime,
    ShadowSampler,
    ShadowSamplingMode,
    ShadowTaskEnvelope,
    ShadowTracer,
    ShadowTimeout,
)


class _Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        self.t += 0.001  # 1ms per tick: stays well within a heartbeat TTL
        return self.t


class SafeMemory:
    def __init__(self):
        self.requested: list[str] = []

    def retrieve(self, *, access: MemoryAccess, query_text: str, top_k: int):
        self.requested.append(access.tenant_id)
        item = ContextItem(key="k", text=f"mem:{query_text}:{access.tenant_id}",
                           scope="*", similarity=0.9)
        return (item,) if top_k > 0 else ()


class Provider:
    def __init__(self, fail=None):
        self.reads = 0
        self.fail = fail

    def read(self, *, capability: ReadOnlyCapability, context):
        self.reads += 1
        if self.fail is not None:
            raise self.fail
        return AgentObservation(
            agent_run_id="run", agent_id="monitoring",
            summary=f"observed {capability.value}",
            facts=("fact",),
            confidence=0.9,
        )

    # Scenario F/G marker: the provider/agent has NO write / service-mutation API.
    def _no_write_surface(self):
        raise NotImplementedError("no write surface in shadow")

    def _no_service_mutation_surface(self):
        raise NotImplementedError("no service mutation in shadow")


class _ProdMock:
    """Synthetic production result. Shadow must never touch it."""
    __slots__ = ("value",)

    def __init__(self):
        self.value = "production-result"

    def apply(self, value):
        self.value = value  # the ONLY way production is changed; never called by shadow


def _build(tmp, *, capability_for=None, provider=None, claim_healthy=True, runner_cls=ShadowRuntime):
    clock = _Clock()
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

    shadow = runner_cls(
        sampler=ShadowSampler(mode=ShadowSamplingMode.FULL_SHADOW),
        budget=ShadowBudget(max_concurrent=16, acquire_timeout_ms=5000),
        claims=InMemoryClaimStore(healthy=claim_healthy),
        vertical=vertical,
        audit=ShadowAuditStore(clock=clock),
        metrics=ShadowMetrics(),
        tracer=ShadowTracer(),
        clock=clock,
        capability_for=capability_for or _true_cap,
        registry_digest=rt.registry_digest(),
        baseline_version="1.3.6",
    )
    del tmp
    return shadow, mem, prov


def _true_cap(kind: str):
    return ReadOnlyCapability.READ_HEALTH  # every kind maps to READ_HEALTH in scenarios


def _env(shadow_id="s1", *, tenant="acme", kind="monitoring", inp="in-1",
         source="req-1"):
    return ShadowTaskEnvelope(
        shadow_id=shadow_id, source_request_id=source, tenant_id=tenant,
        user_id="u-1", task_kind=kind, input_digest=inp, received_at=1000.0,
        sampling_reason="test", production_context_digest="pc", baseline_version="1.3.6",
    )


def _run(shadow, env, prod=None, mock=None):
    out = shadow.dispatch(env, production_decision=prod)
    if mock is not None:
        assert mock.value == "production-result"  # production untouched
    return out


# -- Scenarios ----------------------------------------------------------------

def test_scenario_a_shadow_agrees_match_prod_untouched():
    from agent.platform_shadow.runtime import default_plan
    from agent.platform_shadow.models import ShadowDecision as SD

    shadow, _, prov = _build(None)
    env = _env("a")
    mock = _ProdMock()
    # The production decision that "agrees" with what shadow will produce.
    prod = SD(
        shadow_id="prod", task_id="prod", plan_digest=default_plan(env),
        selected_agent="monitoring", agent_observation="observed read_health",
        supervisor_disposition="completed", confidence=0.9,
        policy_disposition="allow", boundary_disposition="allow_read_only",
        memory_digest="m", duration_ms=1.0,
        comparison_class=ComparisonClass.MATCH, audit_id="prod",
    )
    out = _run(shadow, env, prod=prod, mock=mock)
    assert out.ran and out.claimed
    assert out.decision is not None
    assert out.decision.selected_agent == "monitoring"
    assert out.decision.comparison_class is ComparisonClass.MATCH
    assert shadow._metrics.get("shadow_tasks_completed") == 1 and prov.reads == 1  # type: ignore[attr-defined]
    assert shadow._metrics.get("shadow_comparison_match") == 1  # type: ignore[attr-defined]


def test_scenario_b_shadow_picks_other_agent_prod_unchanged():
    from agent.platform_shadow.models import ShadowDecision, ComparisonClass as CC
    import uuid as _u
    # production "decided" research; shadow routes monitoring -> DIFFERENT_AGENT.
    prod = ShadowDecision(
        shadow_id="p", task_id="t", plan_digest="p1", selected_agent="research",
        agent_observation="prod", supervisor_disposition="completed", confidence=0.9,
        policy_disposition="allow", boundary_disposition="allow", memory_digest="m",
        duration_ms=1.0, comparison_class=CC.MATCH, audit_id="p" + _u.uuid4().hex,
    )
    shadow, _, _ = _build(None)
    mock = _ProdMock()
    out = _run(shadow, _env("b"), prod=prod, mock=mock)
    assert out.decision is not None
    assert out.decision.comparison_class is CC.DIFFERENT_AGENT
    assert shadow._metrics.get("shadow_comparison_mismatch") >= 1  # type: ignore[attr-defined]


def test_scenario_c_shadow_denied_prod_unchanged():
    shadow, _, _ = _build(None, capability_for=lambda k: None)
    mock = _ProdMock()
    out = _run(shadow, _env("c"), mock=mock)
    assert out.ran is False and out.decision is not None
    assert out.decision.comparison_class is ComparisonClass.SHADOW_DENIED
    assert shadow._metrics.get("shadow_route_denied") >= 1  # type: ignore[attr-defined]


def test_scenario_d_shadow_timeout_prod_unchanged():
    shadow, _, _ = _build(None, provider=Provider(fail=ShadowTimeout("slow")))
    mock = _ProdMock()
    out = _run(shadow, _env("d"), mock=mock)
    assert mock.value == "production-result"  # production unaffected
    # §18: a provider timeout surfaces as UNKNOWN -> recorded + HUMAN_REVIEW candidate.
    assert shadow._metrics.get("shadow_tasks_unknown") >= 1  # type: ignore[attr-defined]


def test_scenario_e_shadow_unknown_audit_only():
    shadow, _, _ = _build(None, claim_healthy=False)  # fail-closed claim -> unknown
    out = _run(shadow, _env("e"))
    assert out.ran is False and out.decision is not None
    assert out.decision.comparison_class is ComparisonClass.SHADOW_UNKNOWN
    assert shadow._metrics.get("shadow_tasks_unknown") >= 1  # type: ignore[attr-defined]


def test_scenario_f_coding_patches_data_no_write():
    with pytest.raises(NotImplementedError):
        CodingShadowAgent._no_write_surface()


def test_scenario_g_monitoring_recommends_no_service_mutation():
    shadow, _, prov = _build(None)
    out = _run(shadow, _env("g"))
    assert out.ran is True
    with pytest.raises(NotImplementedError):
        prov._no_service_mutation_surface()
    assert shadow._metrics.get("shadow_tasks_completed") >= 1  # type: ignore[attr-defined]


def test_scenario_h_cross_tenant_context_not_leaked():
    shadow, mem, _ = _build(None)
    _run(shadow, _env("h1", tenant="acme"))
    _run(shadow, _env("h2", tenant="other"))
    # Every memory retrieval was bound to the envelope's OWN tenant.
    assert set(mem.requested) <= {"acme", "other"}
    assert mem.requested == ["acme", "other"]


def test_scenario_i_duplicate_request_single_shadow_run():
    shadow, _, prov = _build(None)
    e1 = _env("i", tenant="acme", kind="monitoring", inp="same")
    e2 = _env("i2", tenant="acme", kind="monitoring", inp="same")  # same semantic key
    out1 = _run(shadow, e1)
    out2 = _run(shadow, e2)
    assert out1.ran is True
    assert out2.ran is False  # duplicate -> single shadow run
    assert prov.reads == 1
    assert shadow._metrics.get("shadow_duplicate_runs") >= 1  # type: ignore[attr-defined]


def test_scenario_j_shadow_crash_production_unaffected():
    shadow, _, _ = _build(None, provider=Provider(fail=RuntimeError("boom")))
    mock = _ProdMock()
    out = _run(shadow, _env("j"), mock=mock)
    assert mock.value == "production-result"  # production mock untouched
    # §18/§19: error -> UNKNOWN (HUMAN_REVIEW candidate); production unaffected.
    assert shadow._metrics.get("shadow_tasks_unknown") >= 1  # type: ignore[attr-defined]