"""A1 authority-sealing adversarial tests.

The executor is a runtime-private, non-authoritative adapter primitive.  The
only way to execute an adapter is through a ``LimitedRestartRuntime`` that has
issued an internal capability.  Every attempt to construct, copy, replay, or
redeem an execution grant outside the issuing runtime instance must be denied
with the adapter never running (``adapter_calls == 0``).
"""
from __future__ import annotations

import copy
import pickle
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
    RestartProfileRegistry,
)
from agent.service_restart_policy.executor import BoundedRestartExecutor
from agent.service_restart_policy.runtime import LimitedRestartRuntime, _RestartExecutionGrant

BASELINE = "7218101cf270d6c8f7d67d9f06ddcd41280b1719"


def _ctx(**changes):
    value = AdmissionContext(
        service_id="hermes-aux-canary", profile_version=1, operation="RESTART",
        service_class="HERMES_AUXILIARY", criticality="LOW",
        identity_verified=True, graph_healthy=True, dependents=(),
        consumer=ConsumerClass.NONE, blast_radius=BlastRadius.SERVICE,
        quiescence_proven=True, startup_proven=True,
        health_contract_complete=True, rollback_proven=True, pre_health_ok=True,
        approval_valid=True, old_process_identity="pid/start", graph_digest="g",
        config_digest="config", health_digest="healthy", risk="HIGH",
        quiescence_contract="q", startup_contract="s", recovery_contract="r",
        budget_snapshot="empty", breaker_snapshot="closed", plan_hash="plan",
        baseline_sha=BASELINE,
    )
    return replace(value, **changes)


def _approval(tx="tx"):
    return ApprovalContract(
        approval_id=f"approval-{tx}", service_id="hermes-aux-canary",
        profile_version=1, transaction_id=tx, old_process_identity="pid/start",
        graph_digest="g", consumer_state="NONE", config_digest="config",
        health_digest="healthy", risk="HIGH", blast="SERVICE",
        quiescence_contract="q", startup_contract="s", recovery_contract="r",
        budget_snapshot="empty", breaker_snapshot="closed", plan_hash="plan",
        baseline_sha=BASELINE, expires_at=200,
    )


def _verified(request):
    return {
        "expected_transition": True, "post_identity": True,
        "config_invariant": True, "graph_invariant": True,
        "health": True, "stabilization": True, "forbidden_side_effect": False,
    }


def _runner_counts(calls):
    def runner(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    return runner


def _capture_runtime(tmp_path, owner_pid=42, owner_start="s42", capture=None):
    """Build a fully authorized runtime that records the internal grant into
    ``capture`` (a dict) via the pre-adapter hook just before adapter runs.
    """
    calls = []
    captured = capture if capture is not None else {}

    runtime = LimitedRestartRuntime(
        tmp_path,
        runner=_runner_counts(calls),
        verifier=_verified,
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=owner_pid,
        owner_start=owner_start,
        process_start=lambda pid: owner_start if pid == owner_pid else None,
        clock=ControlledClock(100, 100),
        per_service_attempts=2,
        per_service_successes=1,
        global_attempts=4,
        global_successes=2,
        pre_adapter_hook=lambda grant: captured.setdefault("grant", grant),
    )
    return runtime, calls, captured


def test_direct_executor_call_without_runtime_grant_is_denied():
    calls = []
    executor = BoundedRestartExecutor(
        RestartProfileRegistry(), runner=_runner_counts(calls),
        rollout_enabled=True, kill_switch=False,
    )
    result = executor.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "tx-direct")
    )
    assert result.outcome == "EXECUTION_AUTHORITY_MISSING"
    assert result.adapter_calls == 0
    assert calls == []


def test_executor_is_not_exported_from_public_package_api():
    import agent.service_restart_policy as package

    assert not hasattr(package, "BoundedRestartExecutor")
    assert "BoundedRestartExecutor" not in package.__all__


@pytest.mark.parametrize(
    "forbidden",
    [
        "_new_execution_authority", "build_execution_grant", "create_executor",
        "issue_grant", "_commit_with_authority", "_new_runtime_idempotency_store",
        "finalize_commit", "mark_committed", "_store_commit",
        "create_grant", "make_executor", "new_grant",
    ],
)
def test_no_external_authority_factory_exists(forbidden):
    import agent.service_restart_policy
    import agent.service_restart_policy.executor
    import agent.service_restart_policy.idempotency
    import agent.service_restart_policy.runtime
    import agent.service_restart_policy.approval

    for module in (
        agent.service_restart_policy,
        agent.service_restart_policy.executor,
        agent.service_restart_policy.idempotency,
        agent.service_restart_policy.runtime,
        agent.service_restart_policy.approval,
    ):
        assert not hasattr(module, forbidden)


def test_hand_made_grant_constructed_externally_is_denied(tmp_path):
    """External code cannot mint a usable authority by construction alone."""
    runtime, calls, _ = _capture_runtime(tmp_path)
    forged = _RestartExecutionGrant(
        transaction_id="tx", service_id="hermes-aux-canary", profile_version=1,
        unit="hermes-aux-canary.service", operation="RESTART",
        plan_hash="plan", approval_id="approval-tx", identity_fingerprint="pid/start",
        graph_digest="g", config_hash="config", risk="HIGH", blast="SERVICE",
        budget_reservation="reservation", lock_nonce="lock", created_monotonic=100,
        expires_monotonic=200, clock_provenance="test", capability_nonce="x",
        instance_token="y", registry_digest=runtime.registry_digest,
    )
    result = runtime.executor.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "tx"), forged
    )
    assert result.outcome == "EXECUTION_AUTHORITY_MISSING"
    assert result.adapter_calls == 0
    assert calls == []


def _authorized_grant(tmp_path):
    runtime, calls, captured = _capture_runtime(tmp_path)
    approval = _approval()
    runtime.approvals.issue_contract(approval)
    request = RestartExecutionRequest("hermes-aux-canary", 1, "tx")
    result = runtime.execute(request, _ctx(), approval)
    assert result.outcome == "COMMITTED"
    assert calls == [1]
    assert "grant" in captured  # pre-adapter hook saw the real internal grant
    return runtime, calls, request, captured["grant"]


def test_copied_and_deepcopied_and_pickled_grants_are_denied(tmp_path):
    runtime, calls, request, grant = _authorized_grant(tmp_path)
    for forged in (
        copy.copy(grant),
        copy.deepcopy(grant),
        pickle.loads(pickle.dumps(grant)),
        replace(grant, plan_hash="wrong"),
        replace(grant, service_id="evil"),
        object(),
    ):
        result = runtime.executor.execute(request, forged)
        assert result.outcome == "EXECUTION_AUTHORITY_MISSING"
        assert result.adapter_calls == 0
    assert calls == [1]  # the adapter ran exactly once (during the legit run)


def test_reused_grant_is_denied_after_single_use(tmp_path):
    runtime, calls, request, grant = _authorized_grant(tmp_path)
    replay = runtime.executor.execute(request, grant)
    assert replay.outcome == "EXECUTION_AUTHORITY_MISSING"
    assert replay.adapter_calls == 0
    assert calls == [1]


def test_wrong_executor_instance_cannot_redeem_runtime_grant(tmp_path):
    runtime, calls, request, grant = _authorized_grant(tmp_path)
    # A separately-constructed executor cannot redeem the runtime's grant even
    # if it claims the same runtime as its (private) owner: the consume check
    # requires the EXACT runtime-owned executor instance.
    outsider = BoundedRestartExecutor(
        RestartProfileRegistry(),
        runner=_runner_counts([]),
        rollout_enabled=True,
        kill_switch=False,
        _runtime_owner=runtime,
    )
    result = outsider.execute(request, grant)
    assert result.outcome == "EXECUTION_AUTHORITY_MISSING"
    assert result.adapter_calls == 0


def test_cross_instance_runtime_grant_is_denied(tmp_path):
    # A6 / cross-instance deny: a capability issued by runtime A is redeemed on
    # runtime B -> denied, adapter 0.
    runtime_a, calls_a, request, grant = _authorized_grant(tmp_path)
    runtime_b, calls_b, _ = _capture_runtime(tmp_path / "b")
    result = runtime_b.executor.execute(request, grant)
    assert result.outcome == "EXECUTION_AUTHORITY_MISSING"
    assert result.adapter_calls == 0
    assert calls_b == []


def test_grant_never_persisted_so_serialized_state_cannot_authorize(tmp_path):
    """The internal grant exists only in the issuing runtime's private in-memory
    registry; durable records never contain anything that could reauthorize the
    adapter after the process is gone or a store snapshot is copied."""
    runtime, calls, request, _ = _authorized_grant(tmp_path)
    durable = runtime.idempotency._tx.read()
    serialized = str(durable)
    # Structured durable record must not smuggle a minted capability.
    assert "capability_nonce" not in serialized
    assert "_RestartExecutionGrant" not in serialized
    # A fresh runtime over the same durable root cannot execute the adapter for
    # the already COMMITTED transaction; it replays, never re-authorizes.
    fresh, calls2, _ = _capture_runtime(tmp_path)
    replay = fresh.execute(request, _ctx(), _approval())
    assert replay.replayed is True
    assert replay.adapter_calls == 0
    assert calls2 == []
