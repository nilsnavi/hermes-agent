"""Offline shadow study and end-to-end fake-runner restart rehearsal."""
from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

from .approval import ApprovalContract
from .lock import HardenedServiceLock
from .models import AdmissionContext, BlastRadius, ConsumerClass, RestartExecutionRequest
from .clock import ControlledClock
from .policy import RestartAdmission
from .registry import RestartProfileRegistry
from .runtime import LimitedRestartRuntime

REHEARSAL_TARGETS = MappingProxyType({
    "success": 50,
    "duplicate": 20,
    "concurrent": 20,
    "stale_lock": 20,
    "pid_reuse": 20,
    "orphan": 20,
    "consumer_critical": 20,
    "graph_drift": 20,
    "health_fail": 20,
    "unknown": 10,
    "breaker": 10,
    "budget": 10,
})

BASELINE = "7218101cf270d6c8f7d67d9f06ddcd41280b1719"


@dataclass(frozen=True)
class ShadowReport:
    evaluations: int
    correct: int
    mutations: int
    subprocess_calls: int
    case_counts: dict[str, int]

    @property
    def correctness(self) -> float:
        return 100.0 * self.correct / self.evaluations if self.evaluations else 0.0


@dataclass(frozen=True)
class RehearsalReport:
    counts: dict[str, int]
    exercised: dict[str, int]
    violations: int
    real_mutations: int
    fake_subprocess_calls: int

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _good() -> AdmissionContext:
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
        old_process_identity="pid/start",
        graph_digest="graph",
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


def _contract(transaction_id: str, approval_id: str | None = None) -> ApprovalContract:
    return ApprovalContract(
        approval_id=approval_id or f"approval-{transaction_id}",
        service_id="hermes-aux-canary",
        profile_version=1,
        transaction_id=transaction_id,
        old_process_identity="pid/start",
        graph_digest="graph",
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
        expires_at=10_000,
    )


def run_shadow_study(root, evaluations: int = 100) -> ShadowReport:
    """Evaluate all required admission families; never construct an executor."""
    if evaluations < 100:
        raise ValueError("shadow study requires at least 100 evaluations")
    admission = RestartAdmission(RestartProfileRegistry())
    cases = (
        ("registered", _good(), "ALLOW_EXACT_REGISTERED_PROFILE"),
        ("unregistered_aux", replace(_good(), service_id="unregistered-aux"), "NOT_REGISTERED"),
        ("gateway", replace(_good(), service_id="hermes-gateway"), "SELF_CONTROL_FORBIDDEN"),
        ("scheduler", replace(_good(), service_id="scheduler", service_class="SCHEDULER"), "NOT_REGISTERED"),
        ("provider", replace(_good(), service_id="provider", service_class="PROVIDER"), "NOT_REGISTERED"),
        ("unknown", replace(_good(), service_id="unknown", service_class="UNKNOWN"), "NOT_REGISTERED"),
        ("stale_graph", replace(_good(), graph_healthy=False), "GRAPH_UNHEALTHY"),
        ("wrong_identity", replace(_good(), identity_verified=False), "IDENTITY_UNVERIFIED"),
        ("consumer_active", replace(_good(), consumer=ConsumerClass.ACTIVE), "CONSUMER_DENIED"),
        ("blast_multi", replace(_good(), blast_radius=BlastRadius.MULTI_SERVICE), "BLAST_RADIUS_DENIED"),
        ("bad_health", replace(_good(), pre_health_ok=False), "PRE_HEALTH_FAILED"),
        ("approval_expired", replace(_good(), approval_valid=False), "APPROVAL_INVALID"),
        ("budget_exhausted", replace(_good(), budget_available=False), "BUDGET_EXCEEDED"),
        ("breaker_open", replace(_good(), breaker_closed=False), "BREAKER_OPEN"),
    )
    correct = 0
    counts = {name: 0 for name, _, _ in cases}
    for index in range(evaluations):
        name, context, expected = cases[index % len(cases)]
        counts[name] += 1
        correct += admission.decide(context).reason == expected
    return ShadowReport(evaluations, correct, 0, 0, counts)


def run_rehearsal(root) -> RehearsalReport:
    """Exercise required scenarios through the composed runtime with fake I/O."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    fake_calls: list[tuple[str, ...]] = []
    fake_calls_lock = threading.Lock()
    violations = 0
    exercised = {name: 0 for name in REHEARSAL_TARGETS}
    exact_argv = ("systemctl", "--user", "restart", "hermes-aux-canary.service")

    def count_call(argv: list[str] | tuple[str, ...]) -> None:
        with fake_calls_lock:
            fake_calls.append(tuple(argv))

    def ok_runner(argv, **kwargs):
        count_call(argv)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    healthy = lambda request: {
        "expected_transition": True, "post_identity": True,
        "config_invariant": True, "graph_invariant": True,
        "health": True, "stabilization": True,
        "forbidden_side_effect": False,
    }

    def runtime_for(path: Path, runner=ok_runner, verifier=healthy, **limits):
        return LimitedRestartRuntime(
            path, runner=runner, verifier=verifier,
            rollout_enabled=True, kill_switch=False,
            owner_pid=42, owner_start="s42",
            process_start=limits.pop("process_start", lambda pid: "s42" if pid == 42 else None),
            per_service_attempts=limits.pop("per_service_attempts", 4),
            per_service_successes=limits.pop("per_service_successes", 2),
            global_attempts=limits.pop("global_attempts", 8),
            global_successes=limits.pop("global_successes", 4),
            clock=limits.pop("clock", ControlledClock(100, 100)),
            **limits,
        )

    def execute(runtime: LimitedRestartRuntime, tx: str, context=None, now=100):
        if isinstance(runtime.clock, ControlledClock):
            runtime.clock.value = now
            runtime.clock.wall_value = now
        approval = _contract(tx)
        runtime.approvals.issue_contract(approval)
        return runtime.execute(
            RestartExecutionRequest("hermes-aux-canary", 1, tx),
            context or _good(), approval,
        )

    for index in range(REHEARSAL_TARGETS["success"]):
        result = execute(runtime_for(root / "success" / str(index)), f"success-{index}")
        violations += (result.outcome, result.adapter_calls) != ("COMMITTED", 1)
        exercised["success"] += 1

    for index in range(REHEARSAL_TARGETS["duplicate"]):
        runtime = runtime_for(root / "duplicate" / str(index))
        tx = f"duplicate-{index}"
        first = execute(runtime, tx)
        duplicate = runtime.execute(
            RestartExecutionRequest("hermes-aux-canary", 1, tx), _good(), _contract(tx)
        )
        violations += (first.outcome, duplicate.outcome, duplicate.adapter_calls) != (
            "COMMITTED", "COMMITTED", 0,
        )
        exercised["duplicate"] += 1

    for index in range(REHEARSAL_TARGETS["concurrent"]):
        scenario = root / "concurrent" / str(index)
        entered = threading.Event()
        release = threading.Event()

        def blocking_runner(argv, **kwargs):
            count_call(argv)
            entered.set()
            release.wait(timeout=2)
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        first_runtime = runtime_for(scenario, runner=blocking_runner)
        second_runtime = runtime_for(scenario)
        first_result = []
        thread = threading.Thread(
            target=lambda: first_result.append(execute(first_runtime, f"concurrent-a-{index}"))
        )
        thread.start()
        entered.wait(timeout=2)
        second = execute(second_runtime, f"concurrent-b-{index}", now=101)
        release.set()
        thread.join(timeout=2)
        violations += not first_result or first_result[0].outcome != "COMMITTED"
        violations += second.outcome != "LOCK_CONFLICT" or second.adapter_calls != 0
        exercised["concurrent"] += 1

    for name in ("stale_lock", "pid_reuse", "orphan"):
        for index in range(REHEARSAL_TARGETS[name]):
            scenario = root / name / str(index)
            starts = {1: "old", 42: "s42"}
            lock = HardenedServiceLock(
                scenario / "locks", process_start=starts.get,
                ttl=1,
            )
            lock.acquire("hermes-aux-canary", 1, "old", "old-nonce", 1)
            if name == "pid_reuse":
                starts[1] = "reused"
            elif name == "orphan":
                starts.pop(1)
            now = 3
            runtime = runtime_for(scenario, process_start=starts.get)
            result = execute(runtime, f"{name}-{index}", now=now)
            expected = ("LOCK_CONFLICT", 0) if name == "stale_lock" else ("COMMITTED", 1)
            violations += (result.outcome, result.adapter_calls) != expected
            exercised[name] += 1

    policy_cases = {
        "consumer_critical": (replace(_good(), consumer=ConsumerClass.CRITICAL), "CONSUMER_DENIED"),
        "graph_drift": (replace(_good(), graph_healthy=False), "GRAPH_UNHEALTHY"),
    }
    for name, (context, expected) in policy_cases.items():
        for index in range(REHEARSAL_TARGETS[name]):
            result = execute(runtime_for(root / name / str(index)), f"{name}-{index}", context)
            violations += result.outcome != expected or result.adapter_calls != 0
            exercised[name] += 1

    unhealthy = lambda request: {
        **healthy(request), "health": False,
    }
    for index in range(REHEARSAL_TARGETS["health_fail"]):
        result = execute(
            runtime_for(root / "health" / str(index), verifier=unhealthy), f"health-{index}"
        )
        violations += result.outcome != "HEALTH_FAILED" or result.adapter_calls != 1
        exercised["health_fail"] += 1

    def timeout_runner(argv, **kwargs):
        count_call(argv)
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 1))

    for index in range(REHEARSAL_TARGETS["unknown"]):
        runtime = runtime_for(root / "unknown" / str(index), runner=timeout_runner)
        tx = f"unknown-{index}"
        first = execute(runtime, tx)
        replay = runtime.execute(
            RestartExecutionRequest("hermes-aux-canary", 1, tx), _good(), _contract(tx)
        )
        violations += (first.outcome, replay.outcome, replay.adapter_calls) != (
            "UNKNOWN_OUTCOME", "UNKNOWN_OUTCOME", 0,
        )
        exercised["unknown"] += 1

    def failed_runner(argv, **kwargs):
        count_call(argv)
        return SimpleNamespace(returncode=7, stdout="", stderr="failed")

    for index in range(REHEARSAL_TARGETS["breaker"]):
        runtime = runtime_for(
            root / "breaker" / str(index), runner=failed_runner, breaker_threshold=1
        )
        first = execute(runtime, f"breaker-a-{index}")
        second = execute(runtime, f"breaker-b-{index}", now=101)
        violations += first.outcome != "ADAPTER_FAILED"
        violations += second.outcome != "BREAKER_OPEN" or second.adapter_calls != 0
        exercised["breaker"] += 1

    for index in range(REHEARSAL_TARGETS["budget"]):
        runtime = runtime_for(
            root / "budget" / str(index),
            per_service_attempts=1, per_service_successes=1,
            global_attempts=1, global_successes=1,
        )
        first = execute(runtime, f"budget-a-{index}")
        second = execute(runtime, f"budget-b-{index}", now=101)
        violations += first.outcome != "COMMITTED"
        violations += second.outcome != "BUDGET_EXCEEDED" or second.adapter_calls != 0
        exercised["budget"] += 1

    violations += sum(call != exact_argv for call in fake_calls)
    return RehearsalReport(
        dict(REHEARSAL_TARGETS), exercised, int(violations),
        real_mutations=0, fake_subprocess_calls=len(fake_calls),
    )


__all__ = [
    "REHEARSAL_TARGETS", "RehearsalReport", "ShadowReport",
    "run_rehearsal", "run_shadow_study",
]
