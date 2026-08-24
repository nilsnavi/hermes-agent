"""Sprint 1.3.17 — adapter outcome contract + pipeline global outcomes."""

from __future__ import annotations

from agent.multi_service_execution.fake_adapter import FakeAdapterResult
from agent.multi_service_execution.models import AdapterOutcome, ChildExecutionState
from agent.multi_service_execution.outcome import (
    adapter_outcome_to_child_state, normalize_adapter_result,
)
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan, make_pipeline,
)


def test_succeeded_never_committed_directly():
    r = adapter_outcome_to_child_state(FakeAdapterResult(AdapterOutcome.ADAPTER_SUCCEEDED, "e"))
    assert r == ChildExecutionState.CHILD_SIMULATED_SUCCEEDED
    assert r != ChildExecutionState.CHILD_TERMINAL


def test_failed_maps_to_failed():
    r = adapter_outcome_to_child_state(FakeAdapterResult(AdapterOutcome.ADAPTER_FAILED, "e", "x"))
    assert r == ChildExecutionState.CHILD_SIMULATED_FAILED


def test_unknown_maps_to_unknown():
    r = adapter_outcome_to_child_state(FakeAdapterResult(AdapterOutcome.ADAPTER_UNKNOWN_OUTCOME))
    assert r == ChildExecutionState.CHILD_SIMULATED_UNKNOWN


def test_malformed_adapter_result_fails_closed():
    normalized = normalize_adapter_result({"not": "a result"})
    assert normalized.outcome == AdapterOutcome.ADAPTER_UNKNOWN_OUTCOME
    assert adapter_outcome_to_child_state(normalized) == ChildExecutionState.CHILD_SIMULATED_UNKNOWN


def test_pipeline_all_success_commits_after_verify(tmp_path):
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    r = pipeline.execute(plan, child_admissions=green_admissions(plan))
    assert r["global_state"] == "SIMULATED_COMMITTED"
    assert r["adapter_call_count"] == 2


def test_pipeline_failed_child_requires_compensation_not_success(tmp_path):
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    scenario = {"svc-b": {"outcome": "ADAPTER_FAILED"}}
    r = pipeline.execute(plan, child_admissions=green_admissions(plan), scenario=scenario)
    assert r["global_state"] == "COMPENSATION_REQUIRED"
    assert r["global_state"] != "SIMULATED_COMMITTED"


def test_pipeline_verify_fail_never_commits(tmp_path):
    from agent.multi_service_execution.verifier import (VerificationResult,
                                                        VerificationState)
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    verify_fail = {"svc-a": VerificationResult(VerificationState.FAILED, "effect_mismatch")}
    r = pipeline.execute(plan, child_admissions=green_admissions(plan),
                         verify_children=verify_fail)
    assert r["global_state"] in ("MANUAL_REVIEW_REQUIRED",)  # verify fail -> manual review
    assert r["adapter_call_count"] == 1


def test_pipeline_stabilization_fail_never_commits(tmp_path):
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    r = pipeline.execute(plan, child_admissions=green_admissions(plan),
                         stabilization_kwargs={"recovery_clean": False})
    assert r["global_state"] == "MANUAL_REVIEW_REQUIRED"


def test_adapter_success_does_not_equal_global_commit(tmp_path):
    # Without a durable claim the adapter is never reached on a duplicate; and
    # the FIRST run must pass verify+stabilize+commit, not just adapter exit.
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    # force verification to fail -> adapter ran (1 call) but global never commits
    from agent.multi_service_execution.verifier import (VerificationResult,
                                                        VerificationState)
    r = pipeline.execute(plan, child_admissions=green_admissions(plan),
                         verify_children={"svc-a":
                             VerificationResult(VerificationState.FAILED, "lock_lost")})
    assert r["adapter_call_count"] == 1
    assert r["global_state"] != "SIMULATED_COMMITTED"