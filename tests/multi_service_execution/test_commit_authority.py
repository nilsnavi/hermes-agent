"""Sprint 1.3.17 — global commit authority and receipts."""

from __future__ import annotations

from agent.multi_service_execution import GlobalExecutionState, semantic_execution_key
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan, make_pipeline,
)


def test_commit_requires_all_children_verified(tmp_path):
    from agent.multi_service_execution.verifier import (VerificationResult,
                                                        VerificationState)
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b", "svc-c")))
    # svc-c fails verification -> not all verified -> no global success
    verify = {s: VerificationResult(VerificationState.VERIFIED, "ok")
              for s in plan.service_set}
    verify["svc-c"] = VerificationResult(VerificationState.FAILED, "health")
    r = pipeline.execute(plan, child_admissions=green_admissions(plan),
                         verify_children=verify)
    assert r["global_state"] != "SIMULATED_COMMITTED"


def test_partial_success_never_presented_as_global(tmp_path):
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    scenario = {"svc-b": {"outcome": "ADAPTER_FAILED"}}
    r = pipeline.execute(plan, child_admissions=green_admissions(plan), scenario=scenario)
    # svc-a succeeded but svc-b failed -> global is COMPENSATION_REQUIRED, not a
    # partial success presented as global success.
    assert r["global_state"] == "COMPENSATION_REQUIRED"


def test_commit_fails_on_lock_loss(tmp_path):
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    r = pipeline.execute(plan, child_admissions=green_admissions(plan),
                         stabilization_kwargs={"locks_valid": False})
    assert r["global_state"] == "MANUAL_REVIEW_REQUIRED"


def test_success_writes_durable_receipt(tmp_path):
    pipeline, runtime, adapter, idem, receipts = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    r = pipeline.execute(plan, child_admissions=green_admissions(plan))
    assert r["global_state"] == "SIMULATED_COMMITTED"
    eid = r["execution_id"]
    rec = receipts.get(eid)
    assert rec is not None
    assert rec["final_disposition"] == "SIMULATED_COMMITTED"
    assert rec["adapter_call_count"] == 2
    assert rec["compensation_required"] is False
    assert receipts.verify(eid) is True
    assert not receipts.verify("nope")


def test_receipt_never_contains_production_mutation(tmp_path):
    pipeline, runtime, adapter, idem, receipts = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    pipeline.execute(plan, child_admissions=green_admissions(plan))
    for rec in receipts.by_global_tx(plan.global_tx_id):
        assert "production" not in str(rec).lower()
        assert rec["mode"] == "rehearsal"


def test_terminal_disposition_recorded_in_idempotency(tmp_path):
    pipeline, runtime, adapter, idem, _ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    r = pipeline.execute(plan, child_admissions=green_admissions(plan))
    st = idem.get(semantic_execution_key(plan))
    assert st is not None
    assert st["state"] == "COMMITTED_SIMULATED"