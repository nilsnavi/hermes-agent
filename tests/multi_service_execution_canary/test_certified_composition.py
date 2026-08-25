from __future__ import annotations

from agent.multi_service_coordination import MultiServiceCoordinator
from agent.multi_service_execution import ExecutionBarrier,GlobalCommitCoordinator
from agent.multi_service_recovery import MultiServiceRecoveryCoordinator
from agent.multi_service_execution_canary import BASELINE_SHA,CERTIFIED_COMPONENTS,CRASH_POINTS,ProductionCanaryRequest,build_canary_pipeline


def _request(name="recovery"):
    return ProductionCanaryRequest.for_exact_canary(request_id=name,baseline_sha=BASELINE_SHA,generation=1,approval_id="approval-"+name,plan_hash="plan-"+name,created_monotonic=1.0,expires_monotonic=1_000_000_000.0)


def test_certified_component_bindings_are_reused_not_reimplemented():
    assert CERTIFIED_COMPONENTS.coordinator is MultiServiceCoordinator
    assert CERTIFIED_COMPONENTS.execution_barrier is ExecutionBarrier
    assert CERTIFIED_COMPONENTS.global_commit is GlobalCommitCoordinator
    assert CERTIFIED_COMPONENTS.recovery_coordinator is MultiServiceRecoveryCoordinator
    assert CERTIFIED_COMPONENTS.real_execution_authority_granted is False


def test_all_ten_crash_points_use_durable_evidence_and_zero_adapter(tmp_path):
    assert len(CRASH_POINTS)==10
    for index,point in enumerate(CRASH_POINTS):
        pipeline=build_canary_pipeline(tmp_path/str(index))
        plan=pipeline.record_crash_evidence(_request(str(index)),point)
        assert plan.adapter_calls==0
        assert plan.real_compensation_adapter_calls==0
        if point=="after-simulated-global-commit":
            assert plan.disposition=="TERMINAL_REPLAY"
        elif point in {"after-child-a","before-child-b","after-child-b","before-verify","after-verify","before-simulated-global-commit"}:
            assert plan.disposition=="COMPENSATION_REQUIRED_SIMULATED"
        else:
            assert plan.disposition=="REVALIDATE_REQUIRED"


def test_empty_or_unknown_recovery_evidence_never_resumes_execution(tmp_path):
    pipeline=build_canary_pipeline(tmp_path)
    req=_request()
    empty=pipeline.recover(req)
    assert empty.disposition=="MANUAL_REVIEW_REQUIRED"
    pipeline.store.append_event(req.semantic_key(),"UNKNOWN_OUTCOME")
    unknown=pipeline.recover(req)
    assert unknown.disposition=="UNKNOWN_OUTCOME"
    assert unknown.manual_review is True
