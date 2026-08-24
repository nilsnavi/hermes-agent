"""A2/A3/A4 adversarial authority-sealing tests.

A2  commit authority is coordinator-owned: the durable store is passive and no
    external path can forge COMMITTED.
A3  the canonical registry is immutable and each runtime holds a construction-
    time snapshot; module rebinding/monkeypatching cannot alter an existing
    runtime's authority, and registry drift is detected via registry_digest.
A4  lock renewal requires a live owner: knowing the lock tuple is never enough.
"""
from __future__ import annotations

import copy
import os
import subprocess
import sys
from dataclasses import replace
from types import MappingProxyType, SimpleNamespace

import pytest

import agent.service_restart_policy.registry as registry_module
from agent.service_restart_policy import (
    AdmissionContext,
    ApprovalContract,
    BlastRadius,
    ConsumerClass,
    ControlledClock,
    RestartExecutionRequest,
    RestartProfileRegistry,
)
from agent.service_restart_policy.approval import DurableApprovalStore
from agent.service_restart_policy.executor import BoundedRestartExecutor
from agent.service_restart_policy.idempotency import DurableIdempotencyStore
from agent.service_restart_policy.lock import HardenedServiceLock, _linux_process_start
from agent.service_restart_policy.runtime import LimitedRestartRuntime

BASELINE = "7218101cf270d6c8f7d67d9f06ddcd41280b1719"
CANARY = "hermes-aux-canary"


def _ctx(**changes):
    value = AdmissionContext(
        service_id=CANARY, profile_version=1, operation="RESTART",
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


def _approval(tx="tx", **changes):
    value = ApprovalContract(
        approval_id=f"approval-{tx}", service_id=CANARY, profile_version=1,
        transaction_id=tx, old_process_identity="pid/start", graph_digest="g",
        consumer_state="NONE", config_digest="config", health_digest="healthy",
        risk="HIGH", blast="SERVICE", quiescence_contract="q", startup_contract="s",
        recovery_contract="r", budget_snapshot="empty", breaker_snapshot="closed",
        plan_hash="plan", baseline_sha=BASELINE, expires_at=200,
    )
    return replace(value, **changes)


def _verified(request):
    return {
        "expected_transition": True, "post_identity": True,
        "config_invariant": True, "graph_invariant": True,
        "health": True, "stabilization": True, "forbidden_side_effect": False,
    }


def _runtime(tmp_path, calls=None, clock=None, owner_pid=42, owner_start="s42"):
    calls = calls if calls is not None else []
    kwargs = dict(
        root=tmp_path,
        runner=lambda *a, **k: calls.append(1) or SimpleNamespace(
            returncode=0, stdout="ok", stderr=""
        ),
        verifier=_verified,
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=owner_pid,
        owner_start=owner_start,
        process_start=lambda pid: owner_start if pid == owner_pid else None,
        clock=clock or ControlledClock(100, 100),
        per_service_attempts=2,
        per_service_successes=1,
        global_attempts=4,
        global_successes=2,
    )
    return LimitedRestartRuntime(**kwargs)


# --------------------------------------------------------------------------- #
# A2 — commit authority is coordinator-owned
# --------------------------------------------------------------------------- #

def test_direct_store_committed_write_is_rejected(tmp_path):
    store = DurableIdempotencyStore(tmp_path)
    store.claim("key", 100, "owner")
    with pytest.raises(PermissionError):
        store.transition("key", "owner", {"CLAIMED"}, "COMMITTED", 101)
    with pytest.raises(PermissionError):
        store.commit("key", "COMMITTED", 101, "owner")
    rec = store.get("key")
    assert rec is not None and rec["state"] != "COMMITTED"


def test_external_object_cannot_drive_coordinator_commit(tmp_path):
    runtime = _runtime(tmp_path)
    # No commit-ready token was ever minted for this key, and the caller is not
    # the runtime: coordinator_commit must reject.
    with pytest.raises(PermissionError):
        runtime.idempotency.coordinator_commit(
            object(), "key", "owner", 101
        )


def test_foreign_runtime_cannot_drive_commit_proof(tmp_path):
    # A2: a different runtime instance cannot redeem A's commit authority.
    runtime_a = _runtime(tmp_path)
    runtime_b = _runtime(tmp_path / "b", owner_pid=43, owner_start="s43")
    approval = _approval()
    runtime_a.approvals.issue_contract(approval)
    request = RestartExecutionRequest(CANARY, 1, "tx")
    assert runtime_a.execute(request, _ctx(), approval).outcome == "COMMITTED"
    # The COMMITTED durable record exists; a second runtime cannot be the one to
    # (re)authorize a COMMITTED transition for a fresh key.
    with pytest.raises(PermissionError):
        runtime_b.idempotency.coordinator_commit(runtime_b, "key", "owner", 101)


def test_commit_requires_runtime_token_not_mere_success(tmp_path):
    runtime = _runtime(tmp_path)
    approval = _approval(tx="t1")
    runtime.approvals.issue_contract(approval)
    request = RestartExecutionRequest(CANARY, 1, "t1")
    assert runtime.execute(request, _ctx(), approval).outcome == "COMMITTED"
    # Re-issuing the same transaction must REPLAY, never double-commit or
    # re-run the adapter (idempotency).
    second = runtime.execute(request, _ctx(), approval)
    assert second.outcome == "COMMITTED"
    assert second.replayed is True
    assert second.adapter_calls == 0


# --------------------------------------------------------------------------- #
# A3 — immutable canonical registry + construction-time snapshot
# --------------------------------------------------------------------------- #

def test_registry_definition_is_immutable():
    assert len(RestartProfileRegistry().entries) == 1
    assert RestartProfileRegistry().service_ids() == (CANARY,)
    with pytest.raises(TypeError):
        registry_module._CANONICAL_ENTRIES["evil"] = object()
    with pytest.raises(TypeError):
        registry_module._CANONICAL_ENTRIES[CANARY] = object()


def test_module_rebind_does_not_change_existing_runtime_authority(tmp_path):
    original = registry_module._CANONICAL_ENTRIES
    runtime = _runtime(tmp_path)
    forged = replace(next(iter(original.values())), service_id="evil",
                     unit_name="attacker.service")
    evil_ctx = replace(_ctx(), service_id="evil", service_class="HERMES_AUXILIARY")
    evil_approval = replace(_approval(), service_id="evil", transaction_id="e",
                            approval_id="approval-e")
    try:
        registry_module._CANONICAL_ENTRIES = MappingProxyType(
            {"evil": forged, CANARY: next(iter(original.values()))}
        )
        # The already-constructed runtime's authority is sealed: it still
        # resolves only the canary and never the forged service.
        assert runtime.registry.resolve("evil") is None
        assert runtime.registry.resolve(CANARY) is not None
        # A REGISTRY_DRIFT signal is exposed via digest comparison.
        assert runtime.registry_digest == runtime.registry.registry_digest
    finally:
        registry_module._CANONICAL_ENTRIES = original


def test_foreign_registry_object_is_rejected_by_executor():
    calls = []
    executor = BoundedRestartExecutor(
        object(), runner=lambda *a, **k: calls.append(1),
        rollout_enabled=True, kill_switch=False,
    )
    result = executor.execute(RestartExecutionRequest("evil", 1, "tx"))
    assert result.outcome == "INVALID_REGISTRY"
    assert calls == []


def test_registry_digest_drift_after_approval_denies_execution(tmp_path):
    """If the registry backing a runtime differs from the digest the plan/
    approval was bound to, execution is denied with REGISTRY_DRIFT."""
    original = registry_module._CANONICAL_ENTRIES
    clean_runtime = _runtime(tmp_path)
    clean_digest = clean_runtime.registry_digest
    bound_ctx = replace(_ctx(), registry_digest=clean_digest)
    bound_approval = replace(_approval(), registry_digest=clean_digest)
    clean_runtime.approvals.issue_contract(bound_approval)
    request = RestartExecutionRequest(CANARY, 1, "tx")
    # Baseline: a runtime on the matching canonical registry commits.
    assert clean_runtime.execute(request, bound_ctx, bound_approval).outcome == "COMMITTED"
    # Now rebind the module registry to a forged definition, then build a NEW
    # runtime that snapshots the modified source -> different digest.
    forged_entry = replace(next(iter(original.values())), unit_name="replaced.service")
    try:
        registry_module._CANONICAL_ENTRIES = MappingProxyType(
            {CANARY: forged_entry}
        )
        drifted = _runtime(tmp_path / "drifted", owner_pid=7, owner_start="s7")
        assert drifted.registry_digest != clean_digest
        drifted.approvals.issue_contract(bound_approval)
        result = drifted.execute(request, bound_ctx, bound_approval)
        # The plan was bound to the ORIGINAL registry digest; this runtime is on
        # a drifted registry -> deny without adapter.
        assert result.outcome == "REGISTRY_DRIFT"
    finally:
        registry_module._CANONICAL_ENTRIES = original


def test_discovery_never_adds_authority(tmp_path):
    discovered = ("scheduler.service", "some-hidden.service", CANARY)
    registry = RestartProfileRegistry(runtime_discovery=lambda: discovered)
    assert registry.service_ids() == (CANARY,)
    assert len(registry.entries) == 1
    # Discovery is observational only.
    assert "scheduler.service" not in registry.entries


# --------------------------------------------------------------------------- #
# A4 — lock renewal requires a live owner (real multiprocess, sec 28)
# --------------------------------------------------------------------------- #

def test_foreign_process_cannot_renew_owner_lock(tmp_path):
    root = str(tmp_path)
    holder = (
        "import os,time;"
        "from agent.service_restart_policy.lock import HardenedServiceLock,_linux_process_start;"
        f"l=HardenedServiceLock({root!r});"
        "pid=os.getpid(); start=_linux_process_start(pid);"
        "print(l.acquire('svc',pid,start,'n1',100,'tx'),flush=True);"
        "time.sleep(1.2)"
    )
    # B reads the lock record and replays the full tuple (tx/pid/start/nonce).
    renewer = (
        "import json,pathlib,time;"
        "from agent.service_restart_policy.lock import HardenedServiceLock;"
        f"l=HardenedServiceLock({root!r});"
        "time.sleep(0.3);"
        "h=json.loads(pathlib.Path(%r+'/service-lock-svc.json').read_text()).get('holder',{});"
        "print('foreign', l.renew('svc',h['transaction_id'],h['pid'],h['start'],h['nonce'],105), flush=True);"
        "print('own-tuple', l.acquire('svc',h['pid'],h['start'],'hijack',105,'hijack'), flush=True)"
    ) % root
    a = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True)
    # Wait for A to acquire before B races.
    assert a.stdout is not None and a.stdout.readline().strip() == "True"
    b = subprocess.run([sys.executable, "-c", renewer], capture_output=True, text=True)
    a.wait(timeout=5)
    out = [line.split()[-1] for line in b.stdout.strip().splitlines()]
    assert out == ["False", "False"]  # renewal denied AND no hijack takeover while owner live


def test_same_pid_but_wrong_start_identity_spoof_denied(tmp_path):
    owner_pid = os.getpid()
    starts = {owner_pid: "real-start"}
    lock = HardenedServiceLock(tmp_path, process_start=starts.get, ttl=10)
    assert lock.acquire("svc", owner_pid, "real-start", "n", 100, "tx")
    # Correct pid and nonce, but the caller claims a forged start identity:
    # the trusted inspector sees the real start -> identity mismatch -> DENY.
    assert not lock.renew("svc", "tx", owner_pid, "forged-start", "n", 105)


def test_dead_owner_renew_denied_and_recovery_is_separate(tmp_path):
    starts = {1: "start"}
    lock = HardenedServiceLock(tmp_path, process_start=starts.get, ttl=10)
    assert lock.acquire("svc", 1, "start", "n", 100, "tx")
    starts.pop(1)  # owner dies
    assert not lock.renew("svc", "tx", 1, "start", "n", 105)  # liveness fails
    # Recovery is NOT renewal: a takeover requires expiry + recovery classifier.
    starts[2] = "start-b"
    assert not lock.acquire("svc", 2, "start-b", "n2", 105, "tx2")  # live window not over
    assert lock.acquire("svc", 2, "start-b", "n2", 111, "tx2")  # after TTL, dead owner taken over


def test_unknown_owner_liveness_fails_closed_on_renew(tmp_path):
    owner_pid = os.getpid()
    starts = {owner_pid: "start"}
    lock = HardenedServiceLock(
        tmp_path, process_start=starts.get, ttl=10,
        owner_liveness=lambda pid, start: "UNKNOWN",
    )
    assert lock.acquire("svc", owner_pid, "start", "n", 100, "tx")
    assert not lock.renew("svc", "tx", owner_pid, "start", "n", 105)


def test_nonce_alone_is_never_sufficient_for_renew(tmp_path):
    owner_pid = os.getpid()
    starts = {owner_pid: "start"}
    lock = HardenedServiceLock(tmp_path, process_start=starts.get, ttl=10)
    assert lock.acquire("svc", owner_pid, "start", "nonce", 100, "tx")
    # Foreign process: same tuple found in the store, but not the live owner.
    assert not lock.renew("svc", "tx", owner_pid + 999, "start", "nonce", 105)
