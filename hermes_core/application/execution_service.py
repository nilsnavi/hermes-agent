"""Tool invocation orchestration without subprocess or registry access."""

from typing import Mapping

from hermes_core.ports.tools import ToolExecutionContext, ToolExecutorPort
from hermes_core.domain.capability import Approval, CapabilityGrant, validate_grant


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
        principal_id: str = "",
        grant: CapabilityGrant | None = None,
        approval: Approval | None = None,
        evaluation_time: int = 0,
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

    def invoke_protected(self, name, arguments, *, principal_id, session_id, turn_id="", tool_call_id="", grant=None, approval=None, evaluation_time=0, approved=False):
        if not name:
            raise ValueError("tool name is required")
        authorization = validate_grant(grant, principal_id=principal_id, session_id=session_id, turn_id=turn_id, tool_call_id=tool_call_id, tool_name=name, arguments=arguments, evaluation_time=evaluation_time, approval=approval)
        if not authorization.authorized:
            raise PermissionError(authorization.reason_code)
        context = ToolExecutionContext(session_id, turn_id, tool_call_id, grant.grant_id, approval is not None)
        return self._executor.invoke(name, arguments, context)
