from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from agent.service_restart_policy import (
    AdmissionContext,
    ApprovalContract,
    BlastRadius,
    ControlledClock,
    ConsumerClass,
    RestartExecutionRequest,
)
from agent.service_restart_policy.runtime import LimitedRestartRuntime

BASELINE = "7218101cf270d6c8f7d67d9f06ddcd41280b1719"


def ctx(approval_valid=True):
    return AdmissionContext(
        service_id="hermes-aux-canary",
        profile_version=1,
        operation="RESTART",
        service_class="HERMES_AUXILIARY",
        criticality="LOW",
        restart_supported=True,
        identity_verified=True,
        graph_healthy=True,
        dependents=(),
        consumer=ConsumerClass.NONE,
        blast_radius=BlastRadius.SERVICE,
        quiescence_proven=True,
        startup_proven=True,
        health_contract_complete=True,
        rollback_proven=True,
        pre_health_ok=True,
        approval_valid=approval_valid,
        old_process_identity="pid/start",
        graph_digest="g",
        config_digest="config",
        health_digest="healthy",
        risk="HIGH",
        quiescence_contract="q",
        startup_contract="s",
        recovery_contract="r",
        budget_snapshot="empty",
        breaker_snapshot="closed",
        plan_hash="plan",
        baseline_sha=BASELINE,
    )


def contract(approval_id="ap", transaction_id="tx", expires_at=200):
    return ApprovalContract(
        approval_id=approval_id,
        service_id="hermes-aux-canary",
        profile_version=1,
        transaction_id=transaction_id,
        old_process_identity="pid/start",
        graph_digest="g",
        consumer_state="NONE",
        config_digest="config",
        health_digest="healthy",
        risk="HIGH",
        blast="SERVICE",
        quiescence_contract="q",
        startup_contract="s",
        recovery_contract="r",
        budget_snapshot="empty",
        breaker_snapshot="closed",
        plan_hash="plan",
        baseline_sha=BASELINE,
        expires_at=expires_at,
    )


def test_runtime_composes_all_durable_gates_and_cross_process_duplicate(tmp_path):
    calls = []

    def runner(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    kwargs = dict(
        root=tmp_path,
        runner=runner,
        verifier=lambda request: {
            "expected_transition": True, "post_identity": True,
            "config_invariant": True, "graph_invariant": True,
            "health": True, "stabilization": True, "forbidden_side_effect": False,
        },
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=42,
        owner_start="s42",
        process_start=lambda pid: "s42" if pid == 42 else None,
        per_service_attempts=2,
        per_service_successes=1,
        global_attempts=4,
        global_successes=2,
        clock=ControlledClock(100, 100),
    )
    runtime = LimitedRestartRuntime(**kwargs)
    approval = contract()
    runtime.approvals.issue_contract(approval)
    request = RestartExecutionRequest("hermes-aux-canary", 1, "tx")
    result = runtime.execute(request, ctx(), approval)
    assert (result.outcome, result.adapter_calls) == ("COMMITTED", 1)
    duplicate = LimitedRestartRuntime(**kwargs).execute(request, ctx(), approval)
    assert (duplicate.outcome, duplicate.replayed, duplicate.adapter_calls) == (
        "COMMITTED", True, 0,
    )
    assert calls == [1]


def test_runtime_failure_trips_breaker_and_never_retries(tmp_path):
    calls = []

    def runner(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(returncode=7, stdout="", stderr="failed")

    runtime = LimitedRestartRuntime(
        tmp_path,
        runner=runner,
        verifier=lambda request: {
            "expected_transition": True, "post_identity": True,
            "config_invariant": True, "graph_invariant": True,
            "health": True, "stabilization": True, "forbidden_side_effect": False,
        },
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=1,
        owner_start="s",
        process_start=lambda pid: "s",
        breaker_threshold=1,
        per_service_attempts=2,
        per_service_successes=1,
        global_attempts=4,
        global_successes=2,
        clock=ControlledClock(10, 10),
    )
    first_approval = contract("a1", "t1", 99)
    second_approval = contract("a2", "t2", 99)
    runtime.approvals.issue_contract(first_approval)
    runtime.approvals.issue_contract(second_approval)
    first = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "t1"),
        ctx(),
        first_approval,
    )
    second = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "t2"),
        ctx(),
        second_approval,
    )
    assert first.outcome == "ADAPTER_FAILED"
    assert second.outcome == "BREAKER_OPEN"
    assert calls == [1]


def test_post_restart_verifier_gates_commit_and_opens_breaker(tmp_path):
    calls = []
    runtime = LimitedRestartRuntime(
        tmp_path,
        runner=lambda *args, **kwargs: calls.append(1) or SimpleNamespace(
            returncode=0, stdout="ok", stderr=""
        ),
        verifier=lambda request: {
            "expected_transition": True, "post_identity": True,
            "config_invariant": True, "graph_invariant": True,
            "health": False, "stabilization": True, "forbidden_side_effect": False,
        },
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=1,
        owner_start="s",
        process_start=lambda pid: "s",
        breaker_threshold=1,
        clock=ControlledClock(10, 10),
    )
    approval = contract("a1", "t1", 99)
    runtime.approvals.issue_contract(approval)
    result = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "t1"), ctx(), approval
    )
    assert result.outcome == "HEALTH_FAILED"
    assert not runtime.breaker.allow("hermes-aux-canary", 11)
    replay = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "t1"), ctx(), approval
    )
    assert (replay.outcome, replay.adapter_calls, replay.replayed) == (
        "HEALTH_FAILED", 0, True,
    )
    assert calls == [1]


def test_policy_safety_failure_opens_service_breaker_without_adapter(tmp_path):
    calls = []
    runtime = LimitedRestartRuntime(
        tmp_path,
        runner=lambda *args, **kwargs: calls.append(1),
        verifier=lambda request: {
            "expected_transition": True, "post_identity": True,
            "config_invariant": True, "graph_invariant": True,
            "health": True, "stabilization": True, "forbidden_side_effect": False,
        },
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=1,
        owner_start="s",
        process_start=lambda pid: "s",
        breaker_threshold=1,
        clock=ControlledClock(10, 10),
    )
    first_approval = contract("a1", "t1", 99)
    second_approval = contract("a2", "t2", 99)
    runtime.approvals.issue_contract(first_approval)
    runtime.approvals.issue_contract(second_approval)
    unsafe = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "t1"),
        replace(ctx(), quiescence_proven=False),
        first_approval,
    )
    blocked = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "t2"),
        ctx(),
        second_approval,
    )
    assert unsafe.outcome == "QUIESCENCE_UNPROVEN"
    assert blocked.outcome == "BREAKER_OPEN"
    assert calls == []


def test_rollout_enabled_without_post_restart_verifier_is_blocked(tmp_path):
    calls = []
    runtime = LimitedRestartRuntime(
        tmp_path,
        runner=lambda *args, **kwargs: calls.append(1),
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=1,
        owner_start="s",
        process_start=lambda pid: "s",
    )
    approval = contract()
    runtime.approvals.issue_contract(approval)
    result = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "tx"), ctx(), approval
    )
    assert result.outcome == "VERIFIER_REQUIRED"
    assert calls == []


def test_default_runtime_is_production_blocked(tmp_path):
    calls = []
    runtime = LimitedRestartRuntime(
        tmp_path,
        runner=lambda *args, **kwargs: calls.append(1),
        owner_pid=1,
        owner_start="s",
        process_start=lambda pid: "s",
    )
    result = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "tx"),
        ctx(),
        contract(),
    )
    assert result.outcome == "KILL_SWITCH_ACTIVE"
    assert calls == []
