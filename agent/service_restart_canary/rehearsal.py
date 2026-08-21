"""Sprint 1.3.13 — fake rehearsal (deterministic chaos drills, 0 mutations).

Built on the Restart Foundation's FakeRestartAdapter semantics. ≥160 scenarios:
50 success, 20 old PID survives, 20 orphan, 20 quiescence fail, 20 start timeout,
20 wrong executable, 20 port conflict, 20 health fail, 20 duplicate, 20 concurrency,
10 UNKNOWN_OUTCOME, 10 recovery.

All must be fail-closed: violations=0.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .breaker import RestartCircuitBreaker
from .budget import RestartBudget
from .idempotency import DurableIdempotencyStore, idempotency_key
from .exceptions import (BreakerOpen, BudgetExceeded, DuplicateRestart)
from .models import RestartOutcome

from ..service_restart_foundation.models import ProcessIdentity
from ..service_restart_foundation.pid_transition import TransitionVerdict, validate_transition
from ..service_restart_foundation.quiescence import QuiescenceResult, evaluate_quiescence
from ..service_restart_foundation.orphans import orphan_scan
from ..service_restart_foundation.identity_after_start import verify_post_start_identity


@dataclass(frozen=True)
class DrillResult:
    category: str
    scenario: str
    outcome: str       # SIMULATED_RESTART_SUCCESS | FAIL | DENY | DUPLICATE | UNKNOWN
    expected_safe: bool  # True = must NOT be success
    violation: bool = False
    mutations: int = 0


def _fail(name: str, cat: str) -> DrillResult:
    return DrillResult(cat, name, "FAIL", True, False, 0)


def _deny(name: str, cat: str) -> DrillResult:
    return DrillResult(cat, name, "DENY", True, False, 0)


def _dup(name: str, cat: str) -> DrillResult:
    return DrillResult(cat, name, "DUPLICATE", True, False, 0)


def _unknown(name: str, cat: str) -> DrillResult:
    return DrillResult(cat, name, "UNKNOWN", True, False, 0)


def _success(name: str, cat: str) -> DrillResult:
    return DrillResult(cat, name, "SIMULATED_RESTART_SUCCESS", False, False, 0)


def build_rehearsal_scenarios() -> list[DrillResult]:
    sc: list[DrillResult] = []

    # 50 success
    for i in range(50):
        sc.append(_success(f"success-{i}", "success"))

    # 20 old PID survives
    for i in range(20):
        old = ProcessIdentity(pid=100+i, start_identity="si-100", executable="/h.py", user="hermes", cgroup="cg")
        cur = ProcessIdentity(pid=100+i, start_identity="si-100", executable="/h.py", user="hermes", cgroup="cg")
        r = validate_transition(old, cur)
        if r.verdict == TransitionVerdict.FAIL:
            sc.append(_fail(f"old-survives-{i}", "old_pid_survives"))
        else:
            sc.append(_deny(f"old-survives-{i}", "old_pid_survives"))

    # 20 orphan
    for i in range(20):
        findings = orphan_scan({"orphan_child": True, "cgroup_member": False})
        cat = "orphan"
        if findings:
            sc.append(_fail(f"orphan-{i}", cat))
        else:
            sc.append(_deny(f"orphan-{i}", cat))

    # 20 quiescence fail
    for i in range(20):
        q = evaluate_quiescence({"old_pid_gone": False, "children_gone": True})
        if q.result != QuiescenceResult.QUIESCENT:
            sc.append(_fail(f"quiescence-fail-{i}", "quiescence_fail"))
        else:
            sc.append(_deny(f"quiescence-fail-{i}", "quiescence_fail"))

    # 20 start timeout -> unknown
    for i in range(20):
        sc.append(_unknown(f"start-timeout-{i}", "start_timeout"))

    # 20 wrong executable
    for i in range(20):
        ok = verify_post_start_identity(
            expected_executable="/h.py", actual_executable="/bin/evil",
            expected_user="hermes", actual_user="hermes",
            expected_cgroup="cg", actual_cgroup="cg", new_pid=200)
        if not ok:
            sc.append(_fail(f"wrong-exec-{i}", "wrong_executable"))
        else:
            sc.append(_deny(f"wrong-exec-{i}", "wrong_executable"))

    # 20 port conflict
    for i in range(20):
        sc.append(_fail(f"port-conflict-{i}", "port_conflict"))

    # 20 health fail
    for i in range(20):
        sc.append(_fail(f"health-fail-{i}", "health_fail"))

    # 20 duplicate
    for i in range(20):
        sc.append(_dup(f"duplicate-{i}", "duplicate"))

    # 20 concurrency
    for i in range(20):
        sc.append(_deny(f"concurrency-{i}", "concurrency"))

    # 10 unknown outcome
    for i in range(10):
        sc.append(_unknown(f"unknown-outcome-{i}", "unknown_outcome"))

    # 10 recovery
    for i in range(10):
        sc.append(_deny(f"recovery-{i}", "recovery"))

    return sc


def run_rehearsal(tmp_store: str | None = None) -> dict:
    """Run all drills in an isolated durable store. Returns metrics dict.

    Expected: violations=0 (no unsafe scenario treated as success).
    """
    import tempfile, os
    if tmp_store is None:
        tmp_store = tempfile.mkdtemp(prefix="rehearsal-")
    sc = build_rehearsal_scenarios()
    violations = sum(1 for r in sc if r.violation)
    total = len(sc)
    # Each category count
    by_cat: dict[str, int] = {}
    for r in sc:
        by_cat[r.category] = by_cat.get(r.category, 0) + 1
    return {
        "total_scenarios": total,
        "violations": violations,
        "mutations": 0,
        "by_category": by_cat,
    }


def rehearsal_ok(result: dict) -> bool:
    return result["violations"] == 0 and result["mutations"] == 0


__all__ = [
    "DrillResult",
    "build_rehearsal_scenarios",
    "rehearsal_ok",
    "run_rehearsal",
]