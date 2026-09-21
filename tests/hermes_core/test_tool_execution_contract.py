"""Executable C3 contracts for isolated hermes_core tool context propagation."""

from dataclasses import FrozenInstanceError

import pytest

from hermes_core.application.execution_service import ExecutionService
from hermes_core.ports.tools import ToolExecutionContext


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, ToolExecutionContext]] = []

    def invoke(self, name: str, arguments: object, context: ToolExecutionContext) -> object:
        self.calls.append((name, arguments, context))
        return {"ok": True}


def test_execution_service_forwards_exact_tool_arguments_and_logical_context() -> None:
    executor = RecordingExecutor()
    service = ExecutionService(executor)
    arguments = {"path": "workspace/file.txt", "mode": "read"}

    result = service.invoke(
        "read_file",
        arguments,
            session_id="session-1",
            principal_id="principal-1",
        turn_id="turn-2",
        tool_call_id="call-3",
        capability_grant="grant:session-1:read",
        approved=True,
    )

    assert result == {"ok": True}
    assert len(executor.calls) == 1
    name, forwarded_arguments, context = executor.calls[0]
    assert name == "read_file"
    assert forwarded_arguments is arguments
    assert context == ToolExecutionContext(
        session_id="session-1",
        turn_id="turn-2",
        tool_call_id="call-3",
        capability_grant="grant:session-1:read",
        approved=True,
    )


def test_unapproved_protected_execution_is_denied_before_executor() -> None:
    executor = RecordingExecutor()

    with pytest.raises(PermissionError, match="missing_grant"):
        ExecutionService(executor).invoke_protected(
            "inspect",
            {},
        session_id="session-1",
        principal_id="principal-1",
        turn_id="turn-1",
        tool_call_id="call-1",
            grant=None,
            approved=False,
            )
    assert executor.calls == []


def test_tool_execution_context_is_immutable() -> None:
    context = ToolExecutionContext("session", "turn", "call", "grant", True)

    with pytest.raises(FrozenInstanceError):
        context.session_id = "other"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        context.approved = False  # type: ignore[misc]


def test_empty_tool_name_is_rejected_before_executor_call() -> None:
    executor = RecordingExecutor()

    with pytest.raises(ValueError, match="tool name is required"):
        ExecutionService(executor).invoke("", {}, session_id="session")

    assert executor.calls == []
