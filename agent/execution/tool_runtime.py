"""Tool runtime — the single execution interface (Sprint 1.0.2).

``execute()`` NEVER raises for tool problems: handler failures and timeouts
are captured in the returned ToolResult (status failure/timeout). Unknown
tools raise ToolNotAllowed (allowlist). Approval gating is enforced here as
a safety net: ``context={"requires_approval": True, "approved": False}``
yields ``permission_denied`` without invoking the handler.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .exceptions import ToolNotAllowed
from .registry import ToolRegistry

STATUS_SUCCESS = "success"
STATUS_FAILURE = "failure"
STATUS_TIMEOUT = "timeout"
STATUS_PERMISSION_DENIED = "permission_denied"


@dataclass
class ToolResult:
    status: str
    output: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "output": dict(self.output),
            "execution_time": self.execution_time,
            "error": self.error,
        }


class ToolRuntime:
    def __init__(self, registry: ToolRegistry, timeout: float = 30.0) -> None:
        self._registry = registry
        self._timeout = timeout

    def execute(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Run one registered tool and return its result (never raises for
        handler failures). Raises ToolNotAllowed for unknown tools."""
        if not self._registry.has(tool_name):
            raise ToolNotAllowed(tool_name)

        ctx = context or {}
        arguments = arguments or {}

        # Safety net: no silent execution of approval-gated tools.
        if ctx.get("requires_approval") and not ctx.get("approved"):
            return ToolResult(
                status=STATUS_PERMISSION_DENIED,
                error=f"tool {tool_name} requires approval",
            )

        # Arguments validation before execution.
        validator = self._registry.validator(tool_name)
        if validator is not None:
            try:
                validator(arguments)
            except Exception as exc:
                return ToolResult(
                    status=STATUS_FAILURE,
                    error=f"arguments validation failed: {exc}",
                )

        handler = self._registry.get(tool_name)
        # Sprint 1.0.6.2 §27: honor the tool's declared timeout when set
        # (ToolMetadata.timeout), falling back to the runtime default.
        timeout = self._registry.metadata(tool_name).timeout or self._timeout
        started = time.monotonic()
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(handler, arguments, ctx)
        try:
            output = future.result(timeout=timeout)
            return ToolResult(
                status=STATUS_SUCCESS,
                output=output or {},
                execution_time=time.monotonic() - started,
            )
        except TimeoutError:
            pool.shutdown(wait=False, cancel_futures=True)
            return ToolResult(
                status=STATUS_TIMEOUT,
                execution_time=timeout,
                error=f"tool {tool_name} timed out after {timeout}s",
            )
        except Exception as exc:
            pool.shutdown(wait=False, cancel_futures=True)
            return ToolResult(
                status=STATUS_FAILURE,
                execution_time=time.monotonic() - started,
                error=str(exc),
            )
