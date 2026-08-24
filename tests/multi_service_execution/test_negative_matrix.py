"""Sprint 1.3.17 — negative matrix: explicit DENY for high-risk targets/shapes."""

from __future__ import annotations

import pytest

from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_custom_plan, make_coord_plan,
    make_exec_plan, make_pipeline,
)

# shapes the execution layer must NEVER run, in ANY mode
FORBIDDEN_OPS = ["stop", "start", "restart", "signal", "kill", "pkill",
                 "systemctl", "systemctl-restart", "raw-subprocess",
                 "shell-cmd", "os-system", "dynamic-executable",
                 "caller-unit", "caller-command"]
FORBIDDEN_TARGETS = ["gateway", "scheduler", "provider", "database", "db",
                     "network", "auth", "security", "docker", "container",
                     "ssh", "unknown", "unregistered-service"]
FORBIDDEN_BLAST = ["HOST", "NETWORK", "UNKNOWN"]


def _execute(tmp, plan):
    pipeline, *_ = make_pipeline(tmp, env=ENV_REHEARSAL)
    return pipeline.execute(plan, child_admissions=green_admissions(plan))


@pytest.mark.parametrize("op", FORBIDDEN_OPS)
def test_forbidden_generic_control_op_denied(tmp_path, op):
    plan = make_custom_plan("svc-a", operation=op)
    r = _execute(tmp_path, plan)
    assert r["global_state"] == "EXECUTION_DENIED"
    assert r["adapter_call_count"] == 0


@pytest.mark.parametrize("target", FORBIDDEN_TARGETS)
def test_forbidden_target_denied(tmp_path, target):
    plan = make_custom_plan(target)
    r = _execute(tmp_path, plan)
    assert r["global_state"] == "EXECUTION_DENIED"
    assert r["adapter_call_count"] == 0


@pytest.mark.parametrize("blast", FORBIDDEN_BLAST)
def test_forbidden_blast_denied(tmp_path, blast):
    plan = make_custom_plan("svc-a", blast=blast)
    r = _execute(tmp_path, plan)
    assert r["global_state"] == "EXECUTION_DENIED"
    assert r["adapter_call_count"] == 0


def test_raw_subprocess_never_in_source_contract(tmp_path):
    # even a zero-adapter denial must not map to a success for forbidden shapes
    plan = make_custom_plan("svc-a", operation="raw-subprocess")
    r = _execute(tmp_path, plan)
    assert r["global_state"] != "SIMULATED_COMMITTED"


def test_unknown_service_registration_denied(tmp_path):
    # a plan built against a stale registry / unknown service must never run:
    # registry-drift fails the barrier before any adapter.
    plan = make_coord_plan(("svc-a",))
    exec_plan = make_exec_plan(plan)
    r = _execute_drift(tmp_path, exec_plan)
    assert r["global_state"] == "EXECUTION_DENIED"
    assert r["adapter_call_count"] == 0


def _execute_drift(tmp, plan):
    pipeline, *_ = make_pipeline(tmp, env=ENV_REHEARSAL)
    return pipeline.execute(plan, child_admissions=green_admissions(plan),
                            registry_digest_ok=False)