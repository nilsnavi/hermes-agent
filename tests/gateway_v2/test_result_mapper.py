"""Result mapper tests (Sprint 1.0.6 §20-21)."""

from agent.gateway_v2.result_mapper import (
    V2ResultMapper,
    V2_APPROVAL_REQUIRED,
    V2_BUDGET_EXCEEDED,
    V2_EXECUTION_FAILED,
    V2_OK,
)
from agent.orchestrator import OrchestrationResult, StopReason


def _result(stop_reason=None, status="completed", result=None, error=None):
    return OrchestrationResult(
        run_id="run-1", status=status, stop_reason=stop_reason,
        steps_executed=2, tool_calls=2, result=result, error=error,
    )


def test_completed_maps_safe_output():
    result = _result(
        StopReason.COMPLETED,
        result={"step-1": {"status": "success", "output": {"hits": 1},
                           "execution_time": 0.1, "error": None}},
    )
    response = V2ResultMapper().map("req-1", result)
    assert response["ok"] is True
    assert response["code"] == V2_OK
    assert response["output"] == {"step-1": {"hits": 1}}  # ONLY output
    assert "execution_time" not in str(response["output"])
    assert "run_id" not in response  # no internal ids


def test_approval_required_mapped():
    response = V2ResultMapper().map("req-1", _result(StopReason.APPROVAL_REQUIRED,
                                                     status="running"))
    assert response["ok"] is False
    assert response["code"] == V2_APPROVAL_REQUIRED
    assert response["output"] is None


def test_budget_exceeded_mapped():
    response = V2ResultMapper().map("req-1",
                                    _result(StopReason.MAX_TOOL_CALLS, status="running"))
    assert response["code"] == V2_BUDGET_EXCEEDED


def test_execution_failed_mapped_with_safe_error():
    result = _result(StopReason.EXECUTION_FAILED, status="failed",
                     error="step failed: boom")
    response = V2ResultMapper().map("req-1", result)
    assert response["code"] == V2_EXECUTION_FAILED
    assert response["reason"] == "step failed: boom"


def test_none_result_is_internal_error():
    response = V2ResultMapper().map("req-1", None)
    assert response["ok"] is False
    assert response["code"] == "V2_INTERNAL_ERROR"


def test_no_stack_traces_in_response():
    result = _result(StopReason.EXECUTION_FAILED, status="failed",
                     error="Traceback (most recent call last):\n  File ...")
    response = V2ResultMapper().map("req-1", result)
    # errors are mapped to structured codes; the raw traceback stays internal
    assert "Traceback" not in response.get("reason", "")
    assert response["code"] == V2_EXECUTION_FAILED
