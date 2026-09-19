"""Tool invocation orchestration without subprocess or registry access."""

from typing import Mapping

from hermes_core.ports.tools import ToolExecutionContext, ToolExecutorPort


class ExecutionService:
    def __init__(self, executor: ToolExecutorPort) -> None:
        self._executor = executor

    def invoke(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        session_id: str,
        turn_id: str = "",
        tool_call_id: str = "",
        capability_grant: str | None = None,
        approved: bool = False,
    ) -> object:
        if not name:
            raise ValueError("tool name is required")
        context = ToolExecutionContext(
            session_id=session_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            capability_grant=capability_grant,
            approved=approved,
        )
        return self._executor.invoke(name, arguments, context)
