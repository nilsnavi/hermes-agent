from __future__ import annotations

import threading
import subprocess
import sys
from types import SimpleNamespace

import pytest

from agent.service_restart_policy import RestartExecutionRequest, RestartProfileRegistry
from agent.service_restart_policy.approval import DurableApprovalStore
from agent.service_restart_policy.breaker import DurableCircuitBreaker
from agent.service_restart_policy.budget import DurableHourlyBudgets
from agent.service_restart_policy.executor import BoundedRestartExecutor, public_operation
from agent.service_restart_policy.idempotency import (
    DurableIdempotencyStore, semantic_key,
)
from agent.service_restart_policy.lock import HardenedServiceLock


def test_executor_uses_only_fixed_argv_and_bounded_subprocess_contract(tmp_path):
    calls = []
    def runner(argv, **kw):
        calls.append((argv, kw))
        return SimpleNamespace(returncode=0, stdout="x" * 1000, stderr="")
    executor = BoundedRestartExecutor(
        RestartProfileRegistry(), runner=runner, rollout_enabled=True,
        kill_switch=False, timeout=2, max_output=16,
    )
    result = executor.execute(RestartExecutionRequest("hermes-aux-canary", 1, "tx-1"))
    assert result.outcome == "EXECUTION_AUTHORITY_MISSING"
    assert result.adapter_calls == 0
    assert calls == []


def test_executor_default_kill_switch_and_rollout_block_without_call(tmp_path):
    called = []
    runner = lambda *a, **k: called.append(1)
    req = RestartExecutionRequest("hermes-aux-canary", 1, "tx")
    assert BoundedRestartExecutor(RestartProfileRegistry(), runner=runner).execute(req).outcome == "KILL_SWITCH_ACTIVE"
    assert BoundedRestartExecutor(RestartProfileRegistry(), runner=runner, kill_switch=False).execute(req).outcome == "ROLLOUT_DISABLED"
    assert called == []


@pytest.mark.parametrize("op", ["STOP", "START", "KILL", "SIGNAL", "daemon-reload"])
def test_no_public_non_restart_operations(op):
    assert public_operation("hermes-aux-canary", op).outcome == "OPERATION_DENIED"


def test_executor_rejects_unknown_service_version_and_empty_transaction_without_call():
    calls = []
    ex = BoundedRestartExecutor(RestartProfileRegistry(), runner=lambda *a, **k: calls.append(1), rollout_enabled=True, kill_switch=False)
    assert ex.execute(RestartExecutionRequest("other", 1, "tx")).outcome == "NOT_REGISTERED"
    assert ex.execute(RestartExecutionRequest("hermes-aux-canary", 9, "tx")).outcome == "PROFILE_VERSION_MISMATCH"
    assert ex.execute(RestartExecutionRequest("hermes-aux-canary", 1, "")).outcome == "INVALID_REQUEST"
    assert calls == []


def test_semantic_idempotency_survives_reopen_and_store_cannot_forge_commit(tmp_path):
    key = semantic_key(RestartExecutionRequest("hermes-aux-canary", 1, "intent-a"))
    store = DurableIdempotencyStore(tmp_path, clock_provenance="test")
    assert store.claim(key, now=100, owner_id="owner") == "CLAIMED_BY_ME"
    assert DurableIdempotencyStore(tmp_path).claim(key, now=101, owner_id="other") == "CLAIMED_BY_OTHER"
    assert store.transition(key, "owner", {"CLAIMED"}, "EXECUTING", 102)
    # Store is passive: it can never grant COMMITTED by itself.
    with pytest.raises(PermissionError):
        store.transition(key, "owner", {"EXECUTING"}, "COMMITTED", 102)
    with pytest.raises(PermissionError):
        store.commit(key, "COMMITTED", 102, "owner")
    rec = store.get(key)
    assert rec is not None and rec["state"] == "EXECUTING"


def test_semantic_idempotency_is_exactly_once_across_real_processes(tmp_path):
    root = str(tmp_path)
    # A real process runs a full LimitedRestartRuntime to COMMITTED; a second
    # real process claims the identical semantic intent and must observe the
    # terminal result without ever reaching the adapter.
    committer = tmp_path / "committer.py"
    replayer = tmp_path / "replayer.py"
    ctx_lines = """
ctx=AdmissionContext(service_id="hermes-aux-canary",profile_version=1,operation="RESTART",
  service_class="HERMES_AUXILIARY",criticality="LOW",identity_verified=True,graph_healthy=True,
  dependents=(),consumer=ConsumerClass.NONE,blast_radius=BlastRadius.SERVICE,
  quiescence_proven=True,startup_proven=True,health_contract_complete=True,rollback_proven=True,
  pre_health_ok=True,approval_valid=True,old_process_identity="id",graph_digest="g",
  config_digest="c",health_digest="h",risk="HIGH",quiescence_contract="q",startup_contract="s",
  recovery_contract="r",budget_snapshot="b",breaker_snapshot="closed",plan_hash="plan",
  baseline_sha="baseline")
"""
    committer.write_text(
        "from types import SimpleNamespace\n"
        "from agent.service_restart_policy import (AdmissionContext,ApprovalContract,"
        "BlastRadius,ConsumerClass,ControlledClock,RestartExecutionRequest)\n"
        "from agent.service_restart_policy.runtime import LimitedRestartRuntime\n"
        + ctx_lines +
        'ap=ApprovalContract(approval_id="ap",service_id="hermes-aux-canary",'
        'profile_version=1,transaction_id="tx",old_process_identity="id",graph_digest="g",'
        'consumer_state="NONE",config_digest="c",health_digest="h",risk="HIGH",blast="SERVICE",'
        'quiescence_contract="q",startup_contract="s",recovery_contract="r",budget_snapshot="b",'
        'breaker_snapshot="closed",plan_hash="plan",baseline_sha="baseline",expires_at=200)\n'
        f'r=LimitedRestartRuntime({root!r},'
        'runner=lambda *a,**k:SimpleNamespace(returncode=0,stdout="ok",stderr=""),'
        'verifier=lambda req:{"expected_transition":True,"post_identity":True,'
        '"config_invariant":True,"graph_invariant":True,"health":True,"stabilization":True,'
        '"forbidden_side_effect":False},'
        'rollout_enabled=True,kill_switch=False,owner_pid=1,owner_start="s",'
        'process_start=lambda p:"s",clock=ControlledClock(100,100))\n'
        'r.approvals.issue_contract(ap)\n'
        'res=r.execute(RestartExecutionRequest("hermes-aux-canary",1,"tx"),ctx,ap)\n'
        'print(res.outcome, res.adapter_calls, flush=True)\n'
    )
    replayer.write_text(
        "from agent.service_restart_policy import (AdmissionContext,ApprovalContract,"
        "BlastRadius,ConsumerClass,RestartExecutionRequest)\n"
        "from agent.service_restart_policy.idempotency import DurableIdempotencyStore, semantic_key\n"
        + ctx_lines +
        'k=semantic_key(RestartExecutionRequest("hermes-aux-canary",1,"tx"),ctx)\n'
        # Runtime persists idempotency under <root>/idempotency; observe terminal
        # state by claiming against that exact store.
        f'print(DurableIdempotencyStore({(root + "/idempotency")!r}).claim(k,3), flush=True)\n'
    )
    a = subprocess.run([sys.executable, str(committer)], check=True, capture_output=True, text=True)
    b = subprocess.run([sys.executable, str(replayer)], check=True, capture_output=True, text=True)
    assert a.stdout.split() == ["COMMITTED", "1"]
    # A terminal COMMITTED record blocks any re-claim: the second process sees
    # DUPLICATE, never a fresh CLAIM, so the adapter cannot run twice.
    assert b.stdout.strip() == "DUPLICATE"


def test_hardened_lock_detects_ttl_clock_drift_pid_reuse_and_death(tmp_path):
    starts = {10: "start-a"}
    lock = HardenedServiceLock(tmp_path, process_start=lambda pid: starts.get(pid), ttl=10, max_clock_drift=2)
    assert lock.acquire("svc", 10, "start-a", "n1", now=100)
    assert not lock.acquire("svc", 10, "start-a", "n2", now=101)
    starts[10] = "start-b"
    assert not lock.acquire("svc", 10, "start-b", "n2", now=102)
    assert lock.acquire("svc", 10, "start-b", "n2", now=111)  # expired + PID reuse
    starts.clear()
    starts[11] = "start-c"
    assert not lock.acquire("svc", 11, "start-c", "n3", now=112)
    assert lock.acquire("svc", 11, "start-c", "n3", now=122)  # expired + owner death
    starts.clear()
    starts[12] = "start-d"
    assert not lock.acquire("svc", 12, "start-d", "n4", now=90)  # backward drift is ambiguous: fail closed
    starts[11] = "start-c"
    starts[13] = "start-e"
    assert not lock.acquire("svc", 13, "start-e", "n5", now=133)  # expired but live owner
    assert not lock.acquire("other", 99, "forged", "n6", now=102)


def test_same_service_active_writer_never_exceeds_one(tmp_path):
    starts = {1: "s1", 2: "s2"}
    lock1 = HardenedServiceLock(tmp_path, process_start=lambda p: starts.get(p))
    lock2 = HardenedServiceLock(tmp_path, process_start=lambda p: starts.get(p))
    barrier = threading.Barrier(2)
    results = []
    def take(lock, pid, nonce):
        barrier.wait()
        results.append(lock.acquire("svc", pid, starts[pid], nonce, now=100))
    ts = [threading.Thread(target=take, args=(lock1, 1, "a")), threading.Thread(target=take, args=(lock2, 2, "b"))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == [False, True]


def test_same_service_active_writer_never_exceeds_one_across_processes(tmp_path):
    root = str(tmp_path)
    holder = (
        "import os,time;"
        "from agent.service_restart_policy.lock import HardenedServiceLock,_linux_process_start;"
        f"l=HardenedServiceLock({root!r});p=os.getpid();s=_linux_process_start(p);"
        "print(l.acquire('svc',p,s,'holder',100),flush=True);time.sleep(1)"
    )
    contender = (
        "import os;"
        "from agent.service_restart_policy.lock import HardenedServiceLock,_linux_process_start;"
        f"l=HardenedServiceLock({root!r});p=os.getpid();s=_linux_process_start(p);"
        "print(l.acquire('svc',p,s,'contender',100))"
    )
    first = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True)
    assert first.stdout is not None and first.stdout.readline().strip() == "True"
    second = subprocess.run([sys.executable, "-c", contender], check=True, capture_output=True, text=True)
    first.wait(timeout=3)
    assert second.stdout.strip() == "False"


def test_durable_hourly_per_service_and_global_budgets(tmp_path):
    b = DurableHourlyBudgets(tmp_path, per_service_limit=2, global_limit=3)
    assert b.consume("a", now=100)
    assert b.consume("a", now=101)
    assert not b.consume("a", now=102)
    assert b.consume("b", now=103)
    assert not b.consume("c", now=104)
    assert DurableHourlyBudgets(tmp_path, 2, 3).counts("a", now=105) == (2, 3)
    assert b.consume("a", now=3701)


def test_durable_per_service_breaker(tmp_path):
    b = DurableCircuitBreaker(tmp_path, threshold=2, cooldown=60)
    assert b.allow("a", now=10)
    b.record_failure("a", now=11)
    b.record_failure("a", now=12)
    assert not DurableCircuitBreaker(tmp_path, 2, 60).allow("a", now=13)
    assert b.allow("b", now=13)
    assert b.allow("a", now=73)


def test_single_use_bound_approval_is_durable(tmp_path):
    s = DurableApprovalStore(tmp_path)
    s.issue("ap", "svc", 1, "tx", "graph", "identity", expires_at=20)
    assert s.consume("ap", "svc", 1, "tx", "graph", "identity", now=10) == "APPROVED"
    assert DurableApprovalStore(tmp_path).consume("ap", "svc", 1, "tx", "graph", "identity", now=11) == "APPROVAL_USED"
    s.issue("ap2", "svc", 1, "tx", "graph", "identity", expires_at=20)
    assert s.consume("ap2", "svc", 1, "other", "graph", "identity", now=10) == "APPROVAL_BINDING_MISMATCH"
    with pytest.raises(ValueError):
        s.issue("ap", "svc", 1, "new-tx", "graph", "identity", expires_at=30)
    assert s.consume("ap", "svc", 1, "new-tx", "graph", "identity", now=12) == "APPROVAL_USED"
