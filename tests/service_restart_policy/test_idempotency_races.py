import threading
import time
from types import SimpleNamespace

from agent.service_restart_policy import (
    AdmissionContext, ApprovalContract, BlastRadius, ConsumerClass,
    ControlledClock, RestartExecutionRequest,
)
from agent.service_restart_policy.idempotency import DurableIdempotencyStore
from agent.service_restart_policy.runtime import LimitedRestartRuntime


class _Admission:
    def decide(self, context):
        return SimpleNamespace(allowed=True, reason="ALLOWED")


class _Approvals:
    def __init__(self):
        self.validate_calls = 0
        self.consume_calls = 0

    def validate_contract(self, approval, now):
        self.validate_calls += 1
        return "APPROVED"

    def consume_contract(self, approval, now):
        self.consume_calls += 1
        return "APPROVED"


class _Idempotency:
    def __init__(self):
        self.get_calls = 0

    def claim(self, key, now, owner_id, **kwargs):
        return "CLAIMED_BY_ME"

    def get(self, key):
        self.get_calls += 1
        return {"state": "COMMITTED", "outcome": "COMMITTED"}


class _Lock:
    def acquire(self, *args, **kwargs):
        return True

    def release(self, *args, **kwargs):
        return True


class _Budgets:
    def __init__(self):
        self.reserve_calls = 0

    def reserve_attempt(self, service_id, now):
        self.reserve_calls += 1
        return True


class _Breaker:
    def allow(self, service_id, now):
        return True


class _Context:
    service_id = "hermes-aux-canary"
    profile_version = 1
    old_process_identity = "identity"
    graph_digest = "graph"
    consumer = SimpleNamespace(value="NONE")
    config_digest = "config"
    health_digest = "health"
    risk = "HIGH"
    blast_radius = SimpleNamespace(value="SERVICE")
    quiescence_contract = "q"
    startup_contract = "s"
    recovery_contract = "r"
    budget_snapshot = "budget"
    breaker_snapshot = "breaker"
    plan_hash = "plan"
    baseline_sha = "baseline"
    registry_digest = ""


class _Approval:
    approval_id = "approval"
    service_id = "hermes-aux-canary"
    profile_version = 1
    transaction_id = "tx"
    old_process_identity = "identity"
    graph_digest = "graph"
    consumer_state = "NONE"
    config_digest = "config"
    health_digest = "health"
    risk = "HIGH"
    blast = "SERVICE"
    quiescence_contract = "q"
    startup_contract = "s"
    recovery_contract = "r"
    budget_snapshot = "budget"
    breaker_snapshot = "breaker"
    plan_hash = "plan"
    baseline_sha = "baseline"
    registry_digest = ""


def test_duplicate_recheck_after_lock_prevents_second_approval_and_budget(tmp_path):
    runtime = LimitedRestartRuntime(
        tmp_path,
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("adapter must not run")
        ),
        verifier=lambda request: {},
        rollout_enabled=True,
        kill_switch=False,
        owner_pid=1,
        owner_start="start",
        process_start=lambda pid: "start",
        clock=ControlledClock(100, 100),
    )
    runtime.admission = _Admission()
    runtime.approvals = _Approvals()
    runtime.idempotency = _Idempotency()
    runtime.lock = _Lock()
    runtime.budgets = _Budgets()
    runtime.breaker = _Breaker()

    result = runtime.execute(
        RestartExecutionRequest("hermes-aux-canary", 1, "tx"),
        _Context(),
        _Approval(),
    )

    assert result.outcome == "COMMITTED"
    assert result.replayed is True
    assert result.adapter_calls == 0
    assert runtime.idempotency.get_calls == 1
    assert runtime.approvals.validate_calls == 0
    assert runtime.approvals.consume_calls == 0
    assert runtime.budgets.reserve_calls == 0


def _race_context():
    return AdmissionContext(
        service_id="hermes-aux-canary", profile_version=1, operation="RESTART",
        service_class="HERMES_AUXILIARY", criticality="LOW",
        identity_verified=True, graph_healthy=True, dependents=(),
        consumer=ConsumerClass.NONE, blast_radius=BlastRadius.SERVICE,
        quiescence_proven=True, startup_proven=True,
        health_contract_complete=True, rollback_proven=True, pre_health_ok=True,
        approval_valid=True, old_process_identity="identity", graph_digest="graph",
        config_digest="config", health_digest="health", risk="HIGH",
        quiescence_contract="q", startup_contract="s", recovery_contract="r",
        budget_snapshot="budget", breaker_snapshot="closed", plan_hash="plan",
        baseline_sha="baseline",
    )


def _race_approval(index):
    tx = f"tx-{index}"
    return ApprovalContract(
        approval_id=f"approval-{index}", service_id="hermes-aux-canary",
        profile_version=1, transaction_id=tx, old_process_identity="identity",
        graph_digest="graph", consumer_state="NONE", config_digest="config",
        health_digest="health", risk="HIGH", blast="SERVICE",
        quiescence_contract="q", startup_contract="s", recovery_contract="r",
        budget_snapshot="budget", breaker_snapshot="closed", plan_hash="plan",
        baseline_sha="baseline", expires_at=200, plan_expires_at=200,
    )


def _verified(request):
    return {
        "expected_transition": True, "post_identity": True,
        "config_invariant": True, "graph_invariant": True,
        "health": True, "stabilization": True, "forbidden_side_effect": False,
    }


def test_twenty_contenders_same_intent_execute_adapter_and_account_once(tmp_path):
    count = 20
    start = threading.Barrier(count)
    adapter_calls = []
    adapter_lock = threading.Lock()
    results = []
    result_lock = threading.Lock()

    def runner(*args, **kwargs):
        with adapter_lock:
            adapter_calls.append(1)
        time.sleep(0.05)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    runtimes = []
    approvals = []
    for index in range(count):
        pid = 1000 + index
        runtime = LimitedRestartRuntime(
            tmp_path,
            runner=runner,
            verifier=_verified,
            rollout_enabled=True,
            kill_switch=False,
            owner_pid=pid,
            owner_start=f"start-{pid}",
            process_start=lambda value: f"start-{value}",
            clock=ControlledClock(100, 100),
            per_service_attempts=2,
            per_service_successes=1,
            global_attempts=4,
            global_successes=2,
            duplicate_wait=3,
        )
        approval = _race_approval(index)
        runtime.approvals.issue_contract(approval)
        runtimes.append(runtime)
        approvals.append(approval)

    def contend(index):
        start.wait()
        result = runtimes[index].execute(
            RestartExecutionRequest(
                "hermes-aux-canary", 1, f"tx-{index}", intent_id="shared-intent"
            ),
            _race_context(),
            approvals[index],
        )
        with result_lock:
            results.append(result)

    threads = [threading.Thread(target=contend, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert adapter_calls == [1]
    assert len(results) == count
    assert all(result.outcome == "COMMITTED" for result in results)
    assert sum(not result.replayed for result in results) == 1
    assert sum(result.adapter_calls for result in results) == 1
    assert sum(runtime.approvals.owns_consumed_contract(approval)
               for runtime, approval in zip(runtimes, approvals)) == 1
    snapshot = runtimes[0].budgets.snapshot("hermes-aux-canary", 100)
    assert snapshot == {
        "service_attempts": 1, "service_successes": 1,
        "global_attempts": 1, "global_successes": 1,
    }
    records = runtimes[0].idempotency._tx.read()
    assert len(records) == 1
    assert sum(record.get("state") == "COMMITTED" for record in records.values()) == 1


def test_atomic_claim_barrier_race_repeated_one_hundred_times(tmp_path):
    store = DurableIdempotencyStore(tmp_path)
    for iteration in range(100):
        barrier = threading.Barrier(2)
        outcomes = []

        def claim(owner):
            barrier.wait()
            outcomes.append(store.claim(f"key-{iteration}", 100, owner))

        threads = [
            threading.Thread(target=claim, args=("one",)),
            threading.Thread(target=claim, args=("two",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(outcomes) == ["CLAIMED_BY_ME", "CLAIMED_BY_OTHER"]
