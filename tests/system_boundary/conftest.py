"""Shared fixtures for the system_boundary test suite (Sprint 1.3.3)."""

import sys
from typing import Any, Dict

import pytest

from agent.verified_tool_executor.adapter import AdapterResult
from agent.verified_tool_executor.models import (
    ExecutionContext,
    ExecutionRequest,
    SideEffectReport,
)

# The SBL module is imported lazily by the tests; a missing module must
# surface as an ImportError in the tests (RED phase), not here.

sys.path.insert(0, "agent")


def make_request(
    request_id="req-1",
    run_id="run-1",
    step_id="step-1",
    capability="STATUS_RUNTIME",
    tool_name="runtime_status",
    policy_verdict="ALLOW_V2",
    policy_version="cap-policy-v1",
    policy_decision_id="pd-1",
    arguments=None,
    timeout_ms=2000,
    idempotency_key="idem-1",
    expected_side_effect="READ_ONLY",
    expected_risk_class="READ_ONLY",
    metadata=None,
    intent="status_read",
    intent_subtype="runtime",
    operator_context=None,
) -> ExecutionRequest:
    return ExecutionRequest(
        request_id=request_id,
        run_id=run_id,
        step_id=step_id,
        intent=intent,
        intent_subtype=intent_subtype,
        capability=capability,
        tool_name=tool_name,
        policy_version=policy_version,
        policy_decision_id=policy_decision_id,
        policy_verdict=policy_verdict,
        arguments=dict(arguments or {}),
        timeout_ms=timeout_ms,
        idempotency_key=idempotency_key,
        expected_side_effect=expected_side_effect,
        expected_risk_class=expected_risk_class,
        metadata=dict(metadata or {}),
        operator_context=(
            dict(operator_context) if operator_context else None),
    )


def make_command_request(
    tool_name: str = "runtime_status",
    command: str = "echo hi",
    capability: str = "STATUS_RUNTIME",
    expected_side_effect: str = "READ_ONLY",
    expected_risk_class: str = "READ_ONLY",
    **kw: Any,
) -> ExecutionRequest:
    """A request that carries a shell command in its arguments.

    This mirrors how a future write/exec surface would look: the SBL
    must classify the EFFECTIVE action from the command payload, not
    just the tool name. The executor-side side effect stays READ_ONLY
    (the migrated surface); the boundary still inspects the payload.
    """
    args = dict(kw.get("arguments") or {})
    args.setdefault("command", command)
    return make_request(
        tool_name=tool_name,
        capability=capability,
        arguments=args,
        expected_side_effect=expected_side_effect,
        expected_risk_class=expected_risk_class,
        **{k: v for k, v in kw.items() if k != "arguments"},
    )


class DummyAdapter:
    """Adapter used by integration tests; records calls."""

    def __init__(self):
        self.calls = 0

    def execute(self, context: ExecutionContext,
                arguments: Dict[str, Any]) -> AdapterResult:
        self.calls += 1
        return AdapterResult(
            output={"ok": True},
            observed_side_effect=SideEffectReport.READ_ONLY.value,
        )


@pytest.fixture
def request_factory():
    return make_request


@pytest.fixture
def command_request_factory():
    return make_command_request
