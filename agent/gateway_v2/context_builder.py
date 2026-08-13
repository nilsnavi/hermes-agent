"""Gateway V2 request context + TaskContext builder (Sprint 1.0.6).

A :class:`GatewayRequest` is the adapter's view of one inbound request:
correlation id, safe identifiers, goal, tool surface, risk. Raw auth /
session secrets NEVER enter here — the builder only copies whitelisted
metadata fields and scrubs them before they reach TaskContext.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.persistence.redaction import scrub
from agent.runtime.context import TaskContext


@dataclass
class GatewayRequest:
    request_id: str
    user_id: str = ""
    session_id: str = ""
    request_type: str = "chat"
    goal: str = ""
    constraints: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    risk_level: str = "low"
    approval_required: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class GatewayTaskContextBuilder:
    """GatewayRequest → TaskContext, secrets scrubbed, correlation kept."""

    def build(
        self,
        request: GatewayRequest,
        allowed_tools: Optional[List[str]] = None,
    ) -> TaskContext:
        metadata: Dict[str, Any] = {
            "request_id": request.request_id,
            "user_id": request.user_id,
            "session_id": request.session_id,
            "task_type": request.request_type,
        }
        # Copy caller metadata — then scrub EVERYTHING: any auth/session
        # secret (token/api_key/authorization/password/...) becomes
        # [REDACTED] before it can reach the runtime.
        for key, value in request.metadata.items():
            metadata[str(key)] = value
        return TaskContext(
            goal=request.goal,
            constraints=list(request.constraints),
            allowed_tools=list(allowed_tools if allowed_tools is not None
                               else request.allowed_tools),
            risk_level=request.risk_level,
            approval_required=request.approval_required,
            metadata=scrub(metadata),
        )
