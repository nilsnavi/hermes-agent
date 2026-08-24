"""Sprint 1.3.17 — execution plan rules via the pipeline."""

from __future__ import annotations

import pytest

from agent.multi_service_execution import ExecutionMode, build_execution_plan
from agent.multi_service_execution.exceptions import ExecutionDisabled, RevalidateRequired
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, make_coord_plan, make_exec_plan, make_pipeline,
)


def test_flags_off_rejects_execution(tmp_path):
    pipeline, *_ = make_pipeline(
        tmp_path, env={"HERMES_MULTI_SERVICE_EXECUTION_V2_ENABLED": "false",
                       "HERMES_MULTI_SERVICE_EXECUTION_V2_MODE": "rehearsal"})
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    with pytest.raises(ExecutionDisabled):
        pipeline.execute(plan)


def test_unknown_mode_treated_as_off(tmp_path):
    pipeline, *_ = make_pipeline(
        tmp_path, env={"HERMES_MULTI_SERVICE_EXECUTION_V2_ENABLED": "true",
                       "HERMES_MULTI_SERVICE_EXECUTION_V2_MODE": "bogus"})
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    with pytest.raises(ExecutionDisabled):
        pipeline.execute(plan)


def test_live_mode_never_permitted(tmp_path):
    from agent.multi_service_execution import live_execution_permitted
    # even a "canary" mode neither enables live execution nor a simulated path
    assert live_execution_permitted({}) is False
    pipeline, *_ = make_pipeline(
        tmp_path, env={"HERMES_MULTI_SERVICE_EXECUTION_V2_ENABLED": "true",
                       "HERMES_MULTI_SERVICE_EXECUTION_V2_MODE": "canary"})
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    with pytest.raises(ExecutionDisabled):
        pipeline.execute(plan)


def test_expired_plan_raises_revalidate(tmp_path):
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = build_execution_plan(make_coord_plan(("svc-a",)),
                                execution_mode=ExecutionMode.REHEARSAL,
                                now_monotonic=0.0, expires_at_monotonic=5.0)
    with pytest.raises(RevalidateRequired):
        pipeline.execute(plan)  # clock is fixed at 1000.0 -> expired


def test_plan_execution_monotonic(tmp_path):
    from tests.multi_service_execution.conftest import green_admissions
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b", "svc-c")))
    r = pipeline.execute(plan, child_admissions=green_admissions(plan))
    assert r["global_state"] == "SIMULATED_COMMITTED"
    assert r["adapter_call_count"] == 3
    assert r["execution_id"]