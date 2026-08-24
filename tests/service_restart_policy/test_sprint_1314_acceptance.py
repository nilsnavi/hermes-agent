from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest

from agent.service_restart_policy import (
    AdmissionContext,
    BlastRadius,
    ConsumerClass,
    ControlledClock,
    MAX_REGISTERED_RESTART_SERVICES,
    RestartAdmission,
    RestartApprovalPolicy,
    RestartBudget,
    RestartCircuitBreaker,
    RestartProfileRegistry,
)
from agent.service_restart_policy.approval import ApprovalContract, DurableApprovalStore
from agent.service_restart_policy.budget import DurableHourlyBudgets
from agent.service_restart_policy._durable import DurableStateCorrupt
from agent.service_restart_policy.breaker import DurableCircuitBreaker
from agent.service_restart_policy.executor import BoundedRestartExecutor
from agent.service_restart_policy.idempotency import DurableIdempotencyStore
from agent.service_restart_policy.concurrency import RestartConcurrencyPolicy
from agent.service_restart_policy.consumer import RestartConsumerPolicy
from agent.service_restart_policy.evaluation import REHEARSAL_TARGETS, run_rehearsal, run_shadow_study


def good() -> AdmissionContext:
    return AdmissionContext(
        service_id="hermes-aux-canary",
        profile_version=1,
        operation="RESTART",
        service_class="HERMES_AUXILIARY",
        criticality="LOW",
        identity_verified=True,
        graph_healthy=True,
        dependents=(),
        consumer=ConsumerClass.NONE,
        blast_radius=BlastRadius.SERVICE,
        pre_health_ok=True,
        config_valid=True,
        quiescence_proven=True,
        startup_proven=True,
        health_contract_complete=True,
        rollback_proven=True,
        risk_acceptable=True,
        approval_valid=True,
        budget_available=True,
        breaker_closed=True,
        lock_available=True,
        rollout_enabled=True,
        old_process_identity="310281/12311741",
        graph_digest="graph",
        config_digest="config",
        health_digest="healthy",
        risk="HIGH",
        quiescence_contract="q1",
        startup_contract="s1",
        recovery_contract="r1",
        budget_snapshot="b1",
        breaker_snapshot="closed",
        plan_hash="plan",
        baseline_sha="7218101cf270d6c8f7d67d9f06ddcd41280b1719",
    )


def _healthy_verification(request):
    return {
        "expected_transition": True, "post_identity": True,
        "config_invariant": True, "graph_invariant": True,
        "health": True, "stabilization": True, "forbidden_side_effect": False,
    }


def test_named_architecture_components_are_real_policy_types():
    assert MAX_REGISTERED_RESTART_SERVICES == 3
    assert issubclass(RestartBudget, DurableHourlyBudgets)
    assert RestartCircuitBreaker.__name__ == "RestartCircuitBreaker"
    assert issubclass(RestartApprovalPolicy, DurableApprovalStore)


def test_admission_uses_exact_brief_precedence():
    admission = RestartAdmission(RestartProfileRegistry())
    assert admission.PRECEDENCE == (
        "SELF_CONTROL_FORBIDDEN",
        "NOT_REGISTERED",
        "SERVICE_CLASS_DENIED",
        "IDENTITY_UNVERIFIED",
        "PROFILE_VERSION_MISMATCH",
        "GRAPH_UNHEALTHY",
        "CONSUMER_DENIED",
        "DEPENDENCY_DENIED",
        "BLAST_RADIUS_DENIED",
        "PRE_HEALTH_FAILED",
        "CONFIG_INVALID",
        "QUIESCENCE_UNPROVEN",
        "STARTUP_UNPROVEN",
        "RECOVERY_UNPROVEN",
        "RISK_DENIED",
        "APPROVAL_INVALID",
        "BUDGET_EXCEEDED",
        "BREAKER_OPEN",
        "LOCK_CONFLICT",
        "ROLLOUT_DISABLED",
    )
    mutations = (
        dict(service_id="hermes-gateway"),
        dict(service_id="missing"),
        dict(service_class="DATABASE"),
        dict(identity_verified=False),
        dict(profile_version=2),
        dict(graph_healthy=False),
        dict(consumer=ConsumerClass.CRITICAL),
        dict(dependents=("consumer.service",)),
        dict(blast_radius=BlastRadius.UNKNOWN),
        dict(pre_health_ok=False),
        dict(config_valid=False),
        dict(quiescence_proven=False),
        dict(startup_proven=False),
        dict(rollback_proven=False),
        dict(risk_acceptable=False),
        dict(approval_valid=False),
        dict(budget_available=False),
        dict(breaker_closed=False),
        dict(lock_available=False),
        dict(rollout_enabled=False),
    )
    for step, (reason, changes) in enumerate(zip(admission.PRECEDENCE, mutations), 1):
        decision = admission.decide(replace(good(), **changes))
        assert (decision.allowed, decision.reason, decision.step) == (False, reason, step)
    assert admission.decide(good()).allowed


def test_consumer_and_concurrency_policies_fail_closed():
    consumers = RestartConsumerPolicy()
    for value in (ConsumerClass.NONE, ConsumerClass.PASSIVE, ConsumerClass.NON_CRITICAL):
        assert consumers.allowed(value)
    for value in (ConsumerClass.ACTIVE, ConsumerClass.CRITICAL, ConsumerClass.UNKNOWN):
        assert not consumers.allowed(value)
    concurrency = RestartConcurrencyPolicy(live_concurrency_enabled=False)
    assert not concurrency.allowed("a", active_services=("b",), intersecting_graph=False)
    assert not RestartConcurrencyPolicy(live_concurrency_enabled=True).allowed(
        "a", active_services=("b",), intersecting_graph=True
    )
    assert RestartConcurrencyPolicy(live_concurrency_enabled=True).allowed(
        "a", active_services=("b",), intersecting_graph=False
    )


def _approval_contract(**changes) -> ApprovalContract:
    values = dict(
        approval_id="ap",
        service_id="hermes-aux-canary",
        profile_version=1,
        transaction_id="tx",
        old_process_identity="310281/12311741",
        graph_digest="graph",
        consumer_state="NONE",
        config_digest="config",
        health_digest="healthy",
        risk="HIGH",
        blast="SERVICE",
        quiescence_contract="q1",
        startup_contract="s1",
        recovery_contract="r1",
        budget_snapshot="b1",
        breaker_snapshot="closed",
        plan_hash="plan",
        baseline_sha="7218101cf270d6c8f7d67d9f06ddcd41280b1719",
        expires_at=200.0,
    )
    values.update(changes)
    return ApprovalContract(**values)


def test_approval_is_bound_to_full_contract_and_single_use(tmp_path):
    store = DurableApprovalStore(tmp_path)
    contract = _approval_contract()
    store.issue_contract(contract)
    assert store.validate_contract(contract, now=100) == "APPROVED"
    assert store.validate_contract(_approval_contract(config_digest="drift"), now=100) == "APPROVAL_BINDING_MISMATCH"
    assert store.consume_contract(contract, now=100) == "APPROVED"
    assert DurableApprovalStore(tmp_path).consume_contract(contract, now=101) == "APPROVAL_USED"


def test_approval_rejects_none_and_runtime_context_drift_before_adapter(tmp_path):
    from types import SimpleNamespace
    from agent.service_restart_policy.models import RestartExecutionRequest
    from agent.service_restart_policy.runtime import LimitedRestartRuntime

    invalid = _approval_contract(graph_digest=None)
    with pytest.raises(ValueError):
        DurableApprovalStore(tmp_path / "invalid").issue_contract(invalid)

    calls = []
    runtime = LimitedRestartRuntime(
        tmp_path / "runtime",
        runner=lambda *args, **kwargs: calls.append(1) or SimpleNamespace(
            returncode=0, stdout="ok", stderr=""
        ),
        verifier=_healthy_verification,
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=42,
        owner_start="s42",
        process_start=lambda pid: "s42" if pid == 42 else None,
        clock=ControlledClock(100, 100),
    )
    contract = _approval_contract()
    runtime.approvals.issue_contract(contract)
    result = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "tx"),
        replace(good(), graph_digest="runtime-drift"),
        contract,
    )
    assert result.outcome == "APPROVAL_BINDING_MISMATCH"
    assert calls == []


def test_corrupt_durable_state_fails_closed_without_reset(tmp_path):
    budget_root = tmp_path / "budget"
    budget_root.mkdir()
    (budget_root / "hourly-budgets.json").write_text("not-json")
    with pytest.raises(DurableStateCorrupt):
        DurableHourlyBudgets(budget_root).reserve_attempt("svc", 1)

    breaker_root = tmp_path / "breaker"
    breaker_root.mkdir()
    (breaker_root / "circuit-breakers.json").write_text("not-json")
    with pytest.raises(DurableStateCorrupt):
        DurableCircuitBreaker(breaker_root, 1, 60).allow("svc", 1)

    idem_root = tmp_path / "idem"
    idem_root.mkdir()
    (idem_root / "idempotency.json").write_text("not-json")
    with pytest.raises(DurableStateCorrupt):
        DurableIdempotencyStore(idem_root).claim("key", 1)


def test_registry_instance_cannot_be_replaced_or_injected_into_executor():
    registry = RestartProfileRegistry()
    with pytest.raises((AttributeError, TypeError)):
        registry.entries = {"evil": object()}

    calls = []
    executor = BoundedRestartExecutor(
        object(), runner=lambda *args, **kwargs: calls.append(1),
        rollout_enabled=True, kill_switch=False,
    )
    from agent.service_restart_policy.models import RestartExecutionRequest
    result = executor.execute(RestartExecutionRequest("evil", 1, "tx"))
    assert result.outcome == "INVALID_REGISTRY"
    assert calls == []


def test_registry_class_rebind_cannot_expand_executor_authority():
    original = RestartProfileRegistry._ENTRIES
    malicious = replace(
        next(iter(original.values())),
        service_id="evil",
        unit_name="attacker-controlled.service",
    )
    calls = []
    try:
        RestartProfileRegistry._ENTRIES = MappingProxyType({"evil": malicious})
        executor = BoundedRestartExecutor(
            RestartProfileRegistry(),
            runner=lambda *args, **kwargs: calls.append(args),
            rollout_enabled=True,
            kill_switch=False,
        )
        from agent.service_restart_policy.models import RestartExecutionRequest
        result = executor.execute(RestartExecutionRequest("evil", 1, "tx"))
        assert result.outcome == "NOT_REGISTERED"
        assert calls == []
    finally:
        RestartProfileRegistry._ENTRIES = original


def test_nonfinite_time_is_rejected_by_approval_runtime_budget_and_json(tmp_path):
    from types import SimpleNamespace
    from agent.service_restart_policy.models import RestartExecutionRequest
    from agent.service_restart_policy.runtime import LimitedRestartRuntime

    with pytest.raises(ValueError):
        DurableApprovalStore(tmp_path / "approval-inf").issue_contract(
            _approval_contract(expires_at=float("inf"))
        )

    calls = []
    runtime = LimitedRestartRuntime(
        tmp_path / "runtime-nan",
        runner=lambda *args, **kwargs: calls.append(1) or SimpleNamespace(
            returncode=0, stdout="ok", stderr=""
        ),
        verifier=_healthy_verification,
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=42,
        owner_start="s42",
        process_start=lambda pid: "s42" if pid == 42 else None,
        clock=ControlledClock(float("nan"), 100),
    )
    approval = _approval_contract()
    runtime.approvals.issue_contract(approval)
    result = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "tx"),
        good(), approval,
    )
    assert result.outcome == "INVALID_TIME"
    assert calls == []

    with pytest.raises(ValueError):
        DurableHourlyBudgets(tmp_path / "budget-nan").reserve_attempt("svc", float("nan"))

    corrupt = tmp_path / "nan-json"
    corrupt.mkdir()
    (corrupt / "idempotency.json").write_text('{"seen": NaN}')
    with pytest.raises(DurableStateCorrupt):
        DurableIdempotencyStore(corrupt).claim("key", 1)


def test_budget_tracks_attempts_and_successes_per_service_and_global(tmp_path):
    budget = DurableHourlyBudgets(
        tmp_path,
        per_service_attempts=2,
        per_service_successes=1,
        global_attempts=4,
        global_successes=2,
    )
    assert budget.reserve_attempt("a", 100)
    budget.record_success("a", 101)
    assert budget.snapshot("a", 102) == {
        "service_attempts": 1,
        "service_successes": 1,
        "global_attempts": 1,
        "global_successes": 1,
    }
    assert not budget.reserve_attempt("a", 103)  # success cap blocks a second restart
    assert not budget.may_succeed("a", 104)
    assert budget.reserve_attempt("b", 105)
    budget.record_success("b", 106)
    assert not budget.may_succeed("c", 107)


def test_runtime_requires_full_approval_contract_and_replays_without_adapter(tmp_path):
    from types import SimpleNamespace
    from agent.service_restart_policy.models import RestartExecutionRequest
    from agent.service_restart_policy.runtime import LimitedRestartRuntime

    calls = []
    runtime = LimitedRestartRuntime(
        tmp_path,
        runner=lambda *args, **kwargs: calls.append(args) or SimpleNamespace(
            returncode=0, stdout="ok", stderr=""
        ),
        verifier=_healthy_verification,
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=42,
        owner_start="s42",
        process_start=lambda pid: "s42" if pid == 42 else None,
        clock=ControlledClock(100, 100),
    )
    contract = _approval_contract()
    runtime.approvals.issue_contract(contract)
    request = RestartExecutionRequest("hermes-aux-canary", 1, "tx")
    assert runtime.execute(request, good(), contract).outcome == "COMMITTED"
    duplicate = LimitedRestartRuntime(
        tmp_path,
        runner=lambda *args, **kwargs: calls.append(args),
        verifier=_healthy_verification,
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=42,
        owner_start="s42",
        process_start=lambda pid: "s42" if pid == 42 else None,
        clock=ControlledClock(100, 100),
    ).execute(request, good(), contract)
    assert (duplicate.outcome, duplicate.replayed, duplicate.adapter_calls) == ("COMMITTED", True, 0)
    assert len(calls) == 1


def test_shadow_exercises_all_required_case_families(tmp_path):
    report = run_shadow_study(tmp_path, evaluations=112)
    required = {
        "registered", "unregistered_aux", "gateway", "scheduler", "provider", "unknown",
        "stale_graph", "wrong_identity", "consumer_active", "blast_multi", "bad_health",
        "approval_expired", "budget_exhausted", "breaker_open",
    }
    assert required <= set(report.case_counts)
    assert all(report.case_counts[name] > 0 for name in required)
    assert report.correctness == 100.0
    assert report.mutations == report.subprocess_calls == 0


def test_rehearsal_runs_every_required_scenario_not_just_counter_labels(tmp_path):
    report = run_rehearsal(tmp_path)
    assert report.counts == REHEARSAL_TARGETS
    assert report.exercised == REHEARSAL_TARGETS
    assert report.violations == report.real_mutations == 0
    assert report.total == 240
