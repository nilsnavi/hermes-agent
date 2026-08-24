"""Sprint 1.3.17 — system boundary integration (§18)."""

from __future__ import annotations

from agent.system_boundary import block_decision, pass_decision, revalidate_decision
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan, make_pipeline,
)


def _decision_allow(decision) -> bool:
    # a boundary may only deny / raise / require revalidation; an allow pass is
    # the only path that lets execution continue.
    return getattr(decision, "verdict", None) == "PASS"


def test_boundary_pass_allows():
    assert _decision_allow(pass_decision()) is True


def test_boundary_block_denies():
    from agent.system_boundary.models import BoundaryDecision
    d = block_decision(reason_code="HARD_DENIED")
    assert isinstance(d, BoundaryDecision)
    # a block is never an allow
    assert _decision_allow(d) is False


def test_boundary_revalidate_not_allow():
    assert _decision_allow(revalidate_decision(reason_code="stale")) is False


def test_boundary_deny_blocks_pipeline_before_adapter(tmp_path):
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    r = pipeline.execute(plan, child_admissions=green_admissions(plan),
                         boundary_allow=False)
    assert r["adapter_call_count"] == 0
    assert r["global_state"] == "EXECUTION_DENIED"