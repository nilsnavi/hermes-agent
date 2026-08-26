"""Shadow models, sampling, comparison, claim store, guards (Phase 7 §3,§6,§14,§20)."""

import pytest

from agent.platform_shadow.claim_store import ClaimState, InMemoryClaimStore
from agent.platform_shadow.comparison import ComparisonEngine, ComparisonResult
from agent.platform_shadow.guards import (
    IsolationGuard,
    ShadowBudget,
    ShadowOverloaded,
    TimeBudget,
    ShadowTimeout,
)
from agent.platform_shadow.models import (
    ComparisonClass,
    ShadowDecision,
    ShadowSamplingMode,
    ShadowTaskEnvelope,
)
from agent.platform_shadow.sampling import ShadowSampler


def _env(**kw):
    base = dict(
        shadow_id="s-1", source_request_id="req-1", tenant_id="acme",
        user_id="u-1", task_kind="monitoring", input_digest="in-1",
        received_at=1000.0, sampling_reason="reason", production_context_digest="pc",
        baseline_version="1.3.6",
    )
    base.update(kw)
    return ShadowTaskEnvelope(**base)  # type: ignore[arg-type]


# -- models -------------------------------------------------------------------

def test_envelope_is_immutable_data_no_forbidden_fields():
    env = _env()
    assert env.shadow_id == "s-1"
    assert not hasattr(env, "credentials")
    assert not hasattr(env, "secret")
    assert not hasattr(env, "execution_token")
    assert not hasattr(env, "approval_token")
    assert not hasattr(env, "adapter")
    assert not hasattr(env, "executor")


def test_envelope_rejects_blank_required_fields():
    with pytest.raises(ValueError):
        _env(shadow_id="")
    with pytest.raises(ValueError):
        _env(received_at=-1.0)


def test_decision_is_data_never_authority():
    d = ShadowDecision(
        shadow_id="s", task_id="t", plan_digest="p", selected_agent="monitoring",
        agent_observation="ok", supervisor_disposition="completed", confidence=0.9,
        policy_disposition="allow", boundary_disposition="allow", memory_digest="m",
        duration_ms=1.0, comparison_class=ComparisonClass.MATCH, audit_id="a",
    )
    assert d.never_authority() is True
    # No method can override/execute/grant.
    assert not hasattr(d, "override")
    assert not hasattr(d, "execute")
    assert not hasattr(d, "grant")


# -- sampling -----------------------------------------------------------------

def test_sampling_default_off():
    s = ShadowSampler()
    assert s.mode() is ShadowSamplingMode.OFF
    r = s.sample(_env())
    assert r.sampled is False
    assert r.mode is ShadowSamplingMode.OFF


def test_sampling_full_shadow_always():
    s = ShadowSampler(mode=ShadowSamplingMode.FULL_SHADOW)
    assert s.sample(_env()).sampled is True


def test_sampling_full_shadow_respects_task_kind_filter():
    s = ShadowSampler(mode=ShadowSamplingMode.FULL_SHADOW,
                      included_task_kinds=frozenset({"monitoring"}))
    assert s.sample(_env(task_kind="monitoring")).sampled is True
    assert s.sample(_env(task_kind="research")).sampled is False


def test_sampling_sample_mode_is_deterministic_hash_not_caller_authority():
    lo = ShadowSampler(mode=ShadowSamplingMode.SAMPLE, sample_rate_per_mille=1000)
    hi = ShadowSampler(mode=ShadowSamplingMode.SAMPLE, sample_rate_per_mille=0)
    # rate=1000 -> always sampled; rate=0 -> never.
    assert lo.sample(_env()).sampled is True
    assert hi.sample(_env()).sampled is False
    # Deterministic: same input -> same decision.
    a = ShadowSampler(mode=ShadowSamplingMode.SAMPLE, sample_rate_per_mille=500).sample(_env())
    b = ShadowSampler(mode=ShadowSamplingMode.SAMPLE, sample_rate_per_mille=500).sample(_env())
    assert a.sampled == b.sampled


# -- comparison ---------------------------------------------------------------

def _decision(selected="monitoring", plan="p1", disp="completed", obs="ok"):
    return ShadowDecision(
        shadow_id="s", task_id="t", plan_digest=plan, selected_agent=selected,
        agent_observation=obs, supervisor_disposition=disp, confidence=0.9,
        policy_disposition="allow", boundary_disposition="allow", memory_digest="m",
        duration_ms=1.0, comparison_class=ComparisonClass.MATCH, audit_id="a",
    )


def test_comparison_match():
    prod = _decision()
    res = ComparisonEngine.compare(production=prod, shadow=_decision())
    assert res.comparison_class is ComparisonClass.MATCH
    assert res.comparable


def test_comparison_different_agent():
    prod = _decision(selected="research")
    res = ComparisonEngine.compare(production=prod, shadow=_decision(selected="monitoring"))
    assert res.comparison_class is ComparisonClass.DIFFERENT_AGENT


def test_comparison_shadow_denied_not_an_error():
    prod = _decision()
    sh = _decision(selected="monitoring", plan="x")
    sh_denied = ShadowDecision(
        shadow_id="s", task_id="t", plan_digest="p", selected_agent="monitoring",
        agent_observation="", supervisor_disposition="denied", confidence=0.0,
        policy_disposition="denied", boundary_disposition="denied", memory_digest="m",
        duration_ms=1.0, comparison_class=ComparisonClass.SHADOW_DENIED, audit_id="a",
    )
    res = ComparisonEngine.compare(production=prod, shadow=sh_denied)
    assert res.comparison_class is ComparisonClass.SHADOW_DENIED
    # Safety: no auto-correction surface.
    assert ComparisonEngine.safety_assertion() is True



# -- claim store (Phase 7 §10) -------------------------------------------------

def test_claim_single_winner():
    cs = InMemoryClaimStore()
    assert cs.claim("k1", "a").state is ClaimState.WIN
    assert cs.claim("k1", "b").state is ClaimState.LOST_DUPLICATE
    assert cs.claim("k1", "a").state is ClaimState.LOST_DUPLICATE


def test_claim_terminal_replay():
    cs = InMemoryClaimStore()
    assert cs.claim("k1", "a").state is ClaimState.WIN
    cs.terminal("k1")
    # After terminal, an identical later task is a duplicate (replay evidence).
    assert cs.claim("k1", "b").state is ClaimState.LOST_DUPLICATE
    assert cs.is_terminal("k1")


def test_claim_unhealthy_fail_closed():
    cs = InMemoryClaimStore(healthy=False)
    assert cs.claim("k1", "a").state is ClaimState.UNKNOWN


# -- guards -------------------------------------------------------------------

def test_budget_overload_skips_shadow():
    b = ShadowBudget(max_concurrent=1, acquire_timeout_ms=0)
    b.try_acquire_nowait()
    with pytest.raises(ShadowOverloaded):
        b.acquire()
    b.release()
    b.acquire()  # slot free again
    b.release()


def test_time_budget_elapsed():
    tb = TimeBudget(timeout_ms=0)
    with pytest.raises(ShadowTimeout):
        tb.check()


def test_isolation_guard_rejects_production_callable():
    with pytest.raises(Exception):
        IsolationGuard.reject_production_side(lambda: "override", "production_result")
    # A shadow-side read surface is allowed.
    IsolationGuard.reject_production_side(None, "x")
    assert IsolationGuard.is_shadow_side_callable("ReadOnlyProvider") is True