"""Tool invocation orchestration without subprocess or registry access."""

from typing import Mapping

from hermes_core.ports.tools import ToolExecutorPort


class ExecutionService:
    def __init__(self, executor: ToolExecutorPort) -> None:
        self._executor = executor

    def invoke(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        session_id: str,
        approved: bool = False,
    ) -> object:
        if not name:
            raise ValueError("tool name is required")
        return self._executor.invoke(name, arguments, session_id=session_id, approved=approved)
