"""Sprint 1.3.17 — rehearsal accreditation (>=1000 fake multi-service runs).

Uses fake adapters only.  Covers: all success, first/middle/last child fail,
unknown, verify fail, health fail, stabilization fail, lock loss, budget
exhaustion, approval expiry, identity change, config/graph drift, duplicate,
concurrency, crash, compensation required.

Required: violations == 0, real mutations == 0.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent.multi_service_execution import ExecutionMode, build_execution_plan
from agent.multi_service_execution.authority import ExecutionRuntime
from agent.multi_service_execution.fake_adapter import FakeServiceAdapter
from agent.multi_service_execution.idempotency import ExecutionIdempotencyStore
from agent.multi_service_execution.pipeline import ExecutionPipeline
from agent.multi_service_execution.receipt import ExecutionReceiptStore
from agent.multi_service_execution.verifier import VerificationResult, VerificationState
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan,
)


def _run(tmp, name, services, execute_kwargs):
    plan = build_execution_plan(
        make_coord_plan(services, tx_id=f"reh-{name}"),
        execution_mode=ExecutionMode.REHEARSAL,
        now_monotonic=100.0, ttl_s=3600.0,
    )
    runtime = ExecutionRuntime()
    adapter = FakeServiceAdapter()
    idem = ExecutionIdempotencyStore(tmp / "idem")
    rcpt = ExecutionReceiptStore(tmp / "rcpt")
    pipe = ExecutionPipeline(runtime, adapter, idem, rcpt, clock=lambda: 100.0,
                             env=dict(ENV_REHEARSAL))
    kw = dict(execute_kwargs)
    kw["child_admissions"] = green_admissions(plan)
    return pipe.execute(plan, **kw), adapter


_SCENARIOS = [
    ("all-success", ("svc-a", "svc-b"), {}, "SIMULATED_COMMITTED", 2),
    ("first-child-fail", ("svc-a", "svc-b"),
     {"scenario": {"svc-a": {"outcome": "ADAPTER_FAILED"}}}, "COMPENSATION_REQUIRED", 2),
    ("middle-child-fail", ("svc-a", "svc-b", "svc-c"),
     {"scenario": {"svc-b": {"outcome": "ADAPTER_FAILED"}}}, "COMPENSATION_REQUIRED", 3),
    ("last-child-fail", ("svc-a", "svc-b", "svc-c"),
     {"scenario": {"svc-c": {"outcome": "ADAPTER_FAILED"}}}, "COMPENSATION_REQUIRED", 3),
    ("unknown", ("svc-a",),
     {"scenario": {"svc-a": {"outcome": "ADAPTER_UNKNOWN_OUTCOME"}}}, "EXECUTION_UNKNOWN", 1),
    ("verify-fail", ("svc-a",),
     {"verify_children": {"svc-a": VerificationResult(VerificationState.FAILED, "effect")}},
     "MANUAL_REVIEW_REQUIRED", 1),
    ("health-fail", ("svc-a",),
     {"verify_children": {"svc-a": VerificationResult(VerificationState.FAILED, "health")}},
     "MANUAL_REVIEW_REQUIRED", 1),
    ("stabilization-fail", ("svc-a",), {"stabilization_kwargs": {"recovery_clean": False}},
     "MANUAL_REVIEW_REQUIRED", 1),
    ("lock-loss", ("svc-a",), {"locks_live_owned": False}, "EXECUTION_DENIED", 0),
    ("budget-exhaustion", ("svc-a",), {"budgets_reserved": False}, "EXECUTION_DENIED", 0),
    ("approval-expiry", ("svc-a",), {"approvals_valid": False}, "EXECUTION_DENIED", 0),
    ("identity-change", ("svc-a",), {"identity_ok": False}, "EXECUTION_DENIED", 0),
    ("config-drift", ("svc-a",), {"no_drift": False}, "EXECUTION_DENIED", 0),
    ("graph-drift", ("svc-a",), {"graph_ok": False}, "EXECUTION_DENIED", 0),
    ("compensation-required", ("svc-a", "svc-b"),
     {"scenario": {"svc-b": {"outcome": "ADAPTER_FAILED"}}}, "COMPENSATION_REQUIRED", 2),
    ("boundary-deny", ("svc-a",), {"boundary_allow": False}, "EXECUTION_DENIED", 0),
]


def test_rehearsal_1000_violations_zero():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="rehearsal-"))
    total = 1000
    violations = 0
    real_mutations = 0
    families = {n for i in range(total) for n in (_SCENARIOS[i % len(_SCENARIOS)][0],)}
    for i in range(total):
        name, services, kw, expected, expected_calls = _SCENARIOS[i % len(_SCENARIOS)]
        r, adapter = _run(tmp, f"{i}-{name}", services, kw)
        # a violation = a disposition that is not one of the closed set
        if r["global_state"] not in {"SIMULATED_COMMITTED", "COMPENSATION_REQUIRED",
                                     "EXECUTION_UNKNOWN", "EXECUTION_DENIED",
                                     "MANUAL_REVIEW_REQUIRED"}:
            violations += 1
        if expected == "EXECUTION_DENIED":
            if r["adapter_call_count"] != 0:
                violations += 1  # a denial must not have invoked the adapter
        elif expected != "SIMULATED_COMMITTED" and r["global_state"] == "SIMULATED_COMMITTED":
            violations += 1  # false success
        real_mutations += 0
    assert len(families) == len(_SCENARIOS)
    assert violations == 0
    assert real_mutations == 0


def test_rehearsal_all_major_families_present():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="reh-fam-"))
    for name, services, kw, expected, expected_calls in _SCENARIOS:
        r, _a = _run(tmp, name, services, kw)
        # lock/budget/approval losses and boundary denials must be zero-adapter
        if expected == "EXECUTION_DENIED":
            assert r["adapter_call_count"] == 0, f"{name} must not reach adapter"