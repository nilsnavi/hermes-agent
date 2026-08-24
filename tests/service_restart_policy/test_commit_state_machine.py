from __future__ import annotations

import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent.service_restart_policy import (
    AdmissionContext,
    ApprovalContract,
    BlastRadius,
    ConsumerClass,
    ControlledClock,
    RestartExecutionRequest,
)
from agent.service_restart_policy.runtime import LimitedRestartRuntime
from agent.service_restart_policy.idempotency import DurableIdempotencyStore

BASELINE = "7218101cf270d6c8f7d67d9f06ddcd41280b1719"


def _context(**changes):
    value = AdmissionContext(
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
        quiescence_proven=True,
        startup_proven=True,
        health_contract_complete=True,
        rollback_proven=True,
        pre_health_ok=True,
        approval_valid=True,
        old_process_identity="identity",
        graph_digest="graph",
        config_digest="config",
        health_digest="health",
        risk="HIGH",
        quiescence_contract="q",
        startup_contract="s",
        recovery_contract="r",
        budget_snapshot="budget",
        breaker_snapshot="closed",
        plan_hash="plan",
        baseline_sha=BASELINE,
    )
    return replace(value, **changes)


def _approval(tx="tx"):
    return ApprovalContract(
        approval_id=f"approval-{tx}",
        service_id="hermes-aux-canary",
        profile_version=1,
        transaction_id=tx,
        old_process_identity="identity",
        graph_digest="graph",
        consumer_state="NONE",
        config_digest="config",
        health_digest="health",
        risk="HIGH",
        blast="SERVICE",
        quiescence_contract="q",
        startup_contract="s",
        recovery_contract="r",
        budget_snapshot="budget",
        breaker_snapshot="closed",
        plan_hash="plan",
        baseline_sha=BASELINE,
        expires_at=200,
    )


def _verified(**changes):
    result = {
        "expected_transition": True,
        "post_identity": True,
        "config_invariant": True,
        "graph_invariant": True,
        "health": True,
        "stabilization": True,
        "forbidden_side_effect": False,
    }
    result.update(changes)
    return result


def _runtime(tmp_path, verifier, runner=None):
    calls = []

    def default_runner(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    runtime = LimitedRestartRuntime(
        tmp_path,
        runner=runner or default_runner,
        verifier=lambda request: verifier,
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=42,
        owner_start="start",
        process_start=lambda pid: "start" if pid == 42 else None,
        clock=ControlledClock(100, 100),
    )
    approval = _approval()
    runtime.approvals.issue_contract(approval)
    return runtime, approval, calls


@pytest.mark.parametrize(
    ("verification", "expected"),
    [
        (_verified(expected_transition=False), "TRANSITION_NOT_OBSERVED"),
        (_verified(post_identity=False), "IDENTITY_MISMATCH"),
        (_verified(config_invariant=False), "CONFIG_INVARIANT_FAILED"),
        (_verified(graph_invariant=False), "GRAPH_INVARIANT_FAILED"),
        (_verified(health=False), "HEALTH_FAILED"),
        (_verified(stabilization=False), "STABILIZATION_FAILED"),
        (_verified(forbidden_side_effect=True), "FORBIDDEN_SIDE_EFFECT"),
    ],
)
def test_rc_zero_post_verify_failures_are_not_committed(tmp_path, verification, expected):
    runtime, approval, calls = _runtime(tmp_path, verification)
    result = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "tx"),
        _context(),
        approval,
    )
    assert result.outcome == expected
    assert result.outcome != "COMMITTED"
    assert result.adapter_calls == 1
    assert calls == [1]


def test_rc_zero_lock_ownership_lost_before_commit_is_not_committed(tmp_path):
    holder = {}

    def runner(*args, **kwargs):
        runtime = holder["runtime"]
        rec = runtime.lock.holder("hermes-aux-canary")
        assert rec is not None
        assert runtime.lock.release(
            "hermes-aux-canary",
            rec["pid"],
            rec["start"],
            rec["nonce"],
            transaction_id=rec["transaction_id"],
        )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    runtime, approval, _ = _runtime(tmp_path, _verified(), runner=runner)
    holder["runtime"] = runtime
    result = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "tx"), _context(), approval
    )
    assert result.outcome == "COMMIT_AUTHORITY_LOST"
    assert result.outcome != "COMMITTED"
    assert result.adapter_calls == 1


def test_timeout_after_command_is_unknown_and_never_retried(tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append(1)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    runtime, approval, _ = _runtime(tmp_path, _verified(), runner=runner)
    request = RestartExecutionRequest("hermes-aux-canary", 1, "tx")
    first = runtime.execute(request, _context(), approval)
    replay = runtime.execute(request, _context(), approval)
    assert first.outcome == "UNKNOWN_OUTCOME"
    assert replay.outcome == "UNKNOWN_OUTCOME"
    assert replay.adapter_calls == 0
    assert calls == [1]


def test_only_full_verified_chain_is_committed(tmp_path):
    runtime, approval, calls = _runtime(tmp_path, _verified())
    result = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "tx"), _context(), approval
    )
    assert result.outcome == "COMMITTED"
    assert result.adapter_calls == 1
    assert calls == [1]


def test_public_idempotency_store_cannot_forge_committed(tmp_path):
    store = DurableIdempotencyStore(tmp_path)
    assert store.claim("key", 100, "owner") == "CLAIMED_BY_ME"
    with pytest.raises(PermissionError):
        store.commit("key", "COMMITTED", 101, "owner")
    with pytest.raises(PermissionError):
        store.transition("key", "owner", {"CLAIMED"}, "COMMITTED", 101)
    assert store.get("key")["state"] == "CLAIMED"
