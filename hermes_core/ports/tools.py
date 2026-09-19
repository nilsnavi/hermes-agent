"""Tool invocation contract; no subprocess or registry implementation."""

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: str
    turn_id: str
    tool_call_id: str
    capability_grant: str | None
    approved: bool


class ToolExecutorPort(Protocol):
    def invoke(
        self,
        name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> object: ...
