"""Tool invocation contract; no subprocess or registry implementation."""

from typing import Mapping, Protocol


class ToolExecutorPort(Protocol):
    def invoke(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        session_id: str,
        approved: bool = False,
    ) -> object: ...
