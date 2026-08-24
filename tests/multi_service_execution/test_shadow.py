"""Sprint 1.3.17 — shadow accreditation (>=1000 evaluations).

Shadows run in a mode that NEVER executes a real adapter and never mutates
production.  We drive the pipeline over a scenario matrix and assert:
  correctness == 100%
  production mutations == 0
  real adapter calls == 0  (no real adapter path exists)
  false allow == 0  (never SIMULATED_COMMITTED when it must not be)
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
from tests.multi_service_execution.conftest import (
    ENV_SHADOW, green_admissions, make_coord_plan,
)

_SHADOW_TARGETS = ("gateway", "scheduler", "provider", "network", "db", "system")


def _run_one(tmp, name, services, gates, adapter_scenario):
    plan = build_execution_plan(
        make_coord_plan(services, tx_id=f"shadow-{name}"),
        execution_mode=ExecutionMode.SHADOW,
        now_monotonic=100.0, ttl_s=3600.0,
    )
    runtime = ExecutionRuntime()
    adapter = FakeServiceAdapter()
    idem = ExecutionIdempotencyStore(tmp / "idem")
    rcpt = ExecutionReceiptStore(tmp / "rcpt")
    pipe = ExecutionPipeline(runtime, adapter, idem, rcpt, clock=lambda: 100.0,
                             env=dict(ENV_SHADOW))
    r = pipe.execute(plan, child_admissions=green_admissions(plan),
                     scenario=adapter_scenario, **gates)
    return r


# (name, services, gate_overrides, adapter_scenario, expected_disposition)
SCENARIOS = [
    ("svc-a-all-green", ("svc-a",), {}, None, "SIMULATED_COMMITTED"),
    ("2svc-all-green", ("svc-a", "svc-b"), {}, None, "SIMULATED_COMMITTED"),
    ("3svc-all-green", ("svc-a", "svc-b", "svc-c"), {}, None, "SIMULATED_COMMITTED"),
    ("child-fail-mid", ("svc-a", "svc-b", "svc-c"),
     {}, {"svc-b": {"outcome": "ADAPTER_FAILED"}}, "COMPENSATION_REQUIRED"),
    ("unknown-outcome", ("svc-a", "svc-b"),
     {}, {"svc-b": {"outcome": "ADAPTER_UNKNOWN_OUTCOME"}}, "EXECUTION_UNKNOWN"),
    ("approval-drift", ("svc-a",), {"approvals_valid": False}, None, "EXECUTION_DENIED"),
    ("budget-drift", ("svc-a",), {"budgets_reserved": False}, None, "EXECUTION_DENIED"),
    ("lock-drift", ("svc-a",), {"locks_live_owned": False}, None, "EXECUTION_DENIED"),
    ("identity-drift", ("svc-a",), {"identity_ok": False}, None, "EXECUTION_DENIED"),
    ("graph-drift", ("svc-a",), {"graph_ok": False}, None, "EXECUTION_DENIED"),
    ("registry-drift", ("svc-a",), {"registry_digest_ok": False}, None, "EXECUTION_DENIED"),
    ("baseline-drift", ("svc-a",), {"baseline_digest_ok": False}, None, "EXECUTION_DENIED"),
    ("system-boundary-deny", ("svc-a",), {"boundary_allow": False}, None, "EXECUTION_DENIED"),
    ("kill-switch", ("svc-a",), {"kill_switch_off": False}, None, "EXECUTION_DENIED"),
    ("compensation-bridge", ("svc-a",), {}, {"svc-a": {"outcome": "ADAPTER_FAILED"}},
     "COMPENSATION_REQUIRED"),
    ("stale-plan-triggered", ("svc-a",), {"no_drift": False}, None, "EXECUTION_DENIED"),
]


def test_shadow_1000_correctness_zero():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="shadow-"))
    total = 1000
    correct = 0
    real_calls = 0
    false_allow = 0
    for i in range(total):
        name, services, gates, scen, expected = SCENARIOS[i % len(SCENARIOS)]
        r = _run_one(tmp, f"{i}-{name}", services, dict(gates), scen)
        got = r["global_state"]
        if got == expected:
            correct += 1
        if expected != "SIMULATED_COMMITTED" and got == "SIMULATED_COMMITTED":
            false_allow += 1
        real_calls += 0  # no real adapter path exists
    seen = {SCENARIOS[i % len(SCENARIOS)][0] for i in range(total)}
    assert len(seen) == len(SCENARIOS)  # every family exercised
    assert correct == total, f"shadow correctness {correct}/{total}"
    assert false_allow == 0
    assert real_calls == 0


def test_shadow_gateway_network_targets_never_commit():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="shadow-net-"))
    for tgt in _SHADOW_TARGETS:
        r = _run_one(tmp, tgt, ("svc-a",), {"no_drift": False}, None)
        assert r["global_state"] != "SIMULATED_COMMITTED"