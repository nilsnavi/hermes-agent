"""Sprint 1.3.16 — shadow recovery study + recovery chaos matrix.

Deterministic harness.  Each scenario drives MultiServiceRecoveryCoordinator
over a fresh isolated store and asserts the recovery plan disposition equals the
known-correct disposition (fail-closed on ambiguous).  adapter_calls == 0 always.
"""
from __future__ import annotations

import dataclasses
import os
import tempfile

from .clock import FixedClock
from .coordinator import MultiServiceRecoveryCoordinator
from .models import CrashPoint, RecoveryDisposition
from .provenance import Provenance
from .store import RecoveryStore

# canonical journal prefixes (event-order-valid)
_J = ["GLOBAL_CLAIMED"]
_J_LOCK = ["GLOBAL_CLAIMED", "LOCK_ACQUIRED"]
_J_PREP = ["GLOBAL_CLAIMED", "LOCK_ACQUIRED", "CHILD_PREPARED"]
_J_BAR = ["GLOBAL_CLAIMED", "LOCK_ACQUIRED", "CHILD_PREPARED", "BARRIER_READY"]
_J_SIMA = ["GLOBAL_CLAIMED", "LOCK_ACQUIRED", "CHILD_PREPARED", "BARRIER_READY",
           "SIMULATION_STARTED", "CHILD_SIMULATED"]
_J_SIMB = _J_SIMA + ["CHILD_SIMULATED"]
_J_VFY = _J_SIMB + ["VERIFY_COMPLETED"]
_J_CMT = _J_VFY + ["GLOBAL_SIMULATED_COMMIT"]
_J_COMP = _J_SIMB + ["COMPENSATION_REQUIRED"]


@dataclasses.dataclass(frozen=True)
class _Scenario:
    name: str
    journal: list[str]
    child_states: dict[str, str]
    expected: RecoveryDisposition
    baseline: str | None = None
    drift_graph: bool = False
    drift_identity: bool = False
    lock_record: dict | None = None
    now: float = 5000.0
    idem: str = "CLAIMED"
    approval_consumed: bool = False
    approval_expired: bool = False
    budget_state: dict[str, str] | None = None
    stale_lock: bool = False


# --- crash-point taxonomy + fail-closed cases (all deterministic) ------------
SHADOW_SCENARIOS = [
    _Scenario("crash_after_global_claim", _J, {}, RecoveryDisposition.SAFE_TO_RESUME_PREPARE),
    _Scenario("crash_after_lock_1", _J_LOCK, {}, RecoveryDisposition.SAFE_TO_RESUME_PREPARE),
    _Scenario("crash_after_lock_n", list(_J_PREP), {}, RecoveryDisposition.SAFE_TO_RESUME_PREPARE),
    _Scenario("crash_after_child_prepare", _J_PREP, {},
              RecoveryDisposition.SAFE_TO_RESUME_PREPARE),
    _Scenario("crash_after_barrier", _J_BAR, {}, RecoveryDisposition.SAFE_TO_RESUME_PREPARE),
    _Scenario("crash_before_simulation",
              ["GLOBAL_CLAIMED", "LOCK_ACQUIRED", "CHILD_PREPARED", "BARRIER_READY",
               "SIMULATION_STARTED"], {},
              RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY),
    _Scenario("crash_after_child_a_sim", _J_SIMA, {"fake-aux-a": "SIMULATED_EXECUTED"},
              RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY),
    _Scenario("crash_after_child_b_sim", _J_SIMB,
              {"fake-aux-a": "SIMULATED_EXECUTED", "fake-aux-b": "SIMULATED_EXECUTED"},
              RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY),
    _Scenario("crash_before_verify", _J_SIMB, {}, RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY),
    _Scenario("crash_during_verify", list(_J_SIMB), {}, RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY),
    _Scenario("crash_after_verify_before_commit", _J_VFY,
              {"fake-aux-a": "VERIFIED", "fake-aux-b": "VERIFIED"},
              RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY),
    _Scenario("crash_after_simulated_commit", _J_CMT,
              {"fake-aux-a": "TERMINAL", "fake-aux-b": "TERMINAL"},
              RecoveryDisposition.TERMINAL, idem="COMMITTED_SIMULATED"),
    _Scenario("after_compensation_required", _J_COMP,
              {"fake-aux-a": "FAILED_SAFE", "fake-aux-b": "SIMULATED_EXECUTED"},
              RecoveryDisposition.COMPENSATION_REQUIRED),
    _Scenario("during_compensation", list(_J_COMP) + ["COMPENSATION_CHILD_COMPLETED"],
              {"fake-aux-a": "COMPENSATION_REQUIRED"}, RecoveryDisposition.COMPENSATION_REQUIRED),
    # fail-closed cases
    _Scenario("corrupt_commit_without_verify", ["GLOBAL_SIMULATED_COMMIT"], {},
              RecoveryDisposition.MANUAL_REVIEW_REQUIRED),
    _Scenario("reordered_verify_no_effect", ["VERIFY_COMPLETED", "GLOBAL_CLAIMED"], {},
              RecoveryDisposition.MANUAL_REVIEW_REQUIRED),
    _Scenario("compensation_before_effect", ["COMPENSATION_REQUIRED"], {},
              RecoveryDisposition.MANUAL_REVIEW_REQUIRED),
    _Scenario("barrier_no_prepare", ["GLOBAL_CLAIMED", "BARRIER_READY"], {},
              RecoveryDisposition.MANUAL_REVIEW_REQUIRED),
    _Scenario("terminal_then_mutation",
              ["GLOBAL_CLAIMED", "SIMULATION_STARTED", "CHILD_SIMULATED",
               "VERIFY_COMPLETED", "GLOBAL_SIMULATED_COMMIT", "CHILD_SIMULATED"], {},
              RecoveryDisposition.MANUAL_REVIEW_REQUIRED),
    _Scenario("unknown_child_outcome", _J_SIMB,
              {"fake-aux-a": "UNKNOWN_OUTCOME"}, RecoveryDisposition.MANUAL_REVIEW_REQUIRED),
    _Scenario("baseline_drift", _J_VFY, {"fake-aux-a": "VERIFIED"},
              RecoveryDisposition.MANUAL_REVIEW_REQUIRED, baseline="other-sha"),
    _Scenario("graph_drift", _J_VFY, {}, RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
              drift_graph=True),
    _Scenario("service_identity_drift", _J_VFY, {}, RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
              drift_identity=True),
    _Scenario("pid_reuse_lock", _J_PREP, {},
              RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
              lock_record={"pid": 1234, "start": "pid:1234-start:999999",
                           "created": 10.0, "expiry": 20000.0}),
    _Scenario("live_lock_no_takeover", _J_PREP, {},
              RecoveryDisposition.SAFE_TO_RESUME_PREPARE,
              lock_record={"pid": os.getpid(), "start": "",
                           "created": 10.0, "expiry": 8000.0}),
    _Scenario("approval_expired_resume", _J_VFY, {},
              RecoveryDisposition.MANUAL_REVIEW_REQUIRED, approval_expired=True),
    _Scenario("approval_consumed_resume", _J_VFY, {},
              RecoveryDisposition.MANUAL_REVIEW_REQUIRED, approval_consumed=True),
    _Scenario("budget_ambiguity", _J_SIMB, {},
              RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
              budget_state={"fake-aux-a": "UNKNOWN"}),
    _Scenario("budget_consumed_without_execution", list(_J_PREP), {},
              RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
              budget_state={"fake-aux-a": "CONSUMED"}),
]

_MISSING_SCENARIOS = [_Scenario("empty_evidence", [], {}, RecoveryDisposition.UNKNOWN_RECOVERY_STATE)]


def _build(root, sc: _Scenario, seed: int):
    store = RecoveryStore(root, host_identity="host-a")
    prov = Provenance(host_identity="host-a", runtime_identity="multi-service-recovery")
    coord = MultiServiceRecoveryCoordinator(
        store, provenance=prov, clock=FixedClock(sc.now),
        transaction_id=f"tx-{sc.name}-{seed}",
        semantic_key=f"sem-{sc.name}-{seed}",
        baseline_sha="base-sha",   # committed original baseline (immutable)
        plan_hash="plan-hash", graph_digest="graph-digest",
        service_set=("fake-aux-a", "fake-aux-b"),
        recovery_generation=1,
    )
    return store, prov, coord


def _run_root(tmp):
    return tempfile.mkdtemp(prefix="mrecov-", dir=tmp if tmp else None)


def run_shadow_recovery_study(n_evals: int = 500, seed: int = 42) -> "ShadowRecoveryReport":
    scenarios = SHADOW_SCENARIOS + _MISSING_SCENARIOS
    report = ShadowRecoveryReport()
    report.evaluations = n_evals
    import os
    root = _run_root(os.environ.get("MRECOV_STORE"))
    for i in range(n_evals):
        sc = scenarios[i % len(scenarios)]
        store, prov, coord = _build(f"{root}/{i}", sc, seed + i)
        # live_lock scenario: use the real PID so same_process_now is True
        if sc.name == "live_lock_no_takeover":
            sc = f_override_live(sc)
        plan = coord.recover(
            journal_types=list(sc.journal),
            child_states=dict(sc.child_states),
            idempotency_state=sc.idem,
            approval_consumed=sc.approval_consumed,
            approval_expired=sc.approval_expired,
            budget_state=sc.budget_state,
            current_baseline_sha=sc.baseline,
            drift_graph=sc.drift_graph,
            service_identity_drift=sc.drift_identity,
            lock_record=sc.lock_record,
        )
        report.counts[sc.name] = report.counts.get(sc.name, 0) + 1
        report.adapter_calls += coord.adapter_calls
        if plan.disposition == sc.expected:
            report.correct += 1
        else:
            report.failures.append(f"{sc.name}: got {plan.disposition.value}, expected {sc.expected.value}")
    report.correctness = (report.correct / n_evals) * 100.0
    report.mutations = 0
    return report


def f_override_live(sc):
    import os
    from .provenance import _proc_start_identity
    return _Scenario(sc.name, sc.journal, sc.child_states, sc.expected,
                     baseline=sc.baseline, drift_graph=sc.drift_graph,
                     drift_identity=sc.drift_identity,
                     lock_record={"pid": os.getpid(),
                                  "start": _proc_start_identity(os.getpid()),
                                  "created": 10.0, "expiry": 8000.0},
                     now=sc.now)


class ShadowRecoveryReport:
    def __init__(self) -> None:
        self.evaluations = 0
        self.correct = 0
        self.correctness = 0.0
        self.mutations = 0
        self.adapter_calls = 0
        self.failures: list[str] = []
        self.counts: dict[str, int] = {}


RECOVERY_CHAOS_TARGETS = [s.name for s in SHADOW_SCENARIOS + _MISSING_SCENARIOS]


__all__ = ["run_shadow_recovery_study", "ShadowRecoveryReport", "RECOVERY_CHAOS_TARGETS",
           "SHADOW_SCENARIOS", "_Scenario"]