"""Shadow mode (Sprint 1.0.6/1.0.6.1) — observe, never execute.

Shadow builds the TaskContext, validates the plan, evaluates risk /
approval and predicts budgets — via the orchestrator's pure ``dry_run``:
ZERO tool executions, ZERO store writes, in-memory structured summary.
The legacy response stays the source of truth (shadow produces no
user-visible output of its own).

Sprint 1.0.6.1 hardening (§20/§19):
- ``NoExecuteToolRegistry``: any attempt to fetch/execute a handler
  raises :class:`ShadowToolExecutionForbidden` — never relies on the
  "dry_run never executes" convention alone.
- ``default_shadow_registry()``: small READ_ONLY + known-write diagnostic
  surface for the live gateway (which has no production registry wired
  at the hook point). Every handler raises if invoked.
- Hard wall-clock timeout on ``dry_run`` (default 1.0 s); a timeout is
  reported as ``timed_out=True`` + ``shadow.failed`` — legacy unaffected.
"""

import concurrent.futures
import logging
from typing import Any, Dict, List, Optional

from agent.execution.registry import SideEffectClass, ToolMetadata, ToolRegistry
from agent.orchestrator import ExecutionPolicy, RuntimeOrchestrator

from .context_builder import GatewayRequest, GatewayTaskContextBuilder
from .events import SHADOW_COMPLETED, SHADOW_FAILED, SHADOW_STARTED, V2Telemetry
from .exceptions import ShadowToolExecutionForbidden

logger = logging.getLogger("gateway.v2.shadow")


class NoExecuteToolRegistry:
    """Registry VIEW that makes tool execution impossible (§20).

    Inspection calls (``has`` / ``metadata`` / ``names`` / ``is_allowed`` /
    ``validator``) delegate to the base registry — exactly what
    ``orchestrator.dry_run`` needs. Handler access (``get``) and execution
    raise :class:`ShadowToolExecutionForbidden`.
    """

    def __init__(self, base: ToolRegistry) -> None:
        self._base = base

    def has(self, name: str) -> bool:
        return self._base.has(name)

    def is_allowed(self, name: str) -> bool:
        return self._base.is_allowed(name)

    def metadata(self, name: str) -> ToolMetadata:
        return self._base.metadata(name)

    def names(self) -> List[str]:
        return self._base.names()

    def validator(self, name: str):
        return self._base.validator(name)

    def get(self, name: str):  # pragma: no cover — must never run
        raise ShadowToolExecutionForbidden(
            f"shadow mode forbids handler access for tool '{name}'"
        )

    def execute(self, name: str, *args, **kwargs):  # pragma: no cover
        raise ShadowToolExecutionForbidden(
            f"shadow mode forbids tool execution for tool '{name}'"
        )


def _forbidden_handler(name: str):
    def _handler(*args, **kwargs):  # pragma: no cover — must never run
        raise ShadowToolExecutionForbidden(
            f"shadow diagnostic tool '{name}' was invoked"
        )

    return _handler


def default_shadow_registry() -> ToolRegistry:
    """Internal diagnostic shadow surface (read-only + known write tools).

    Used when the live gateway hook has no production registry wired
    (``GatewayV2Adapter(registry=None)``). Tools exist ONLY for plan
    validation / classification; their handlers raise
    ShadowToolExecutionForbidden if ever invoked. Safety beats breadth:
    unknown tools are conservatively classified as write risk.
    """
    reg = ToolRegistry()
    for name in ("search", "runtime_status", "db_read"):
        reg.register(
            name, _forbidden_handler(name),
            metadata=ToolMetadata(idempotent=True,
                                  side_effect_class=SideEffectClass.READ_ONLY),
        )
    reg.register(
        "send_message", _forbidden_handler("send_message"),
        metadata=ToolMetadata(side_effect_class=SideEffectClass.REVERSIBLE_WRITE),
    )
    reg.register(
        "delete_file", _forbidden_handler("delete_file"),
        metadata=ToolMetadata(side_effect_class=SideEffectClass.IRREVERSIBLE_WRITE),
    )
    return reg


class ShadowRunner:
    def __init__(
        self,
        registry: ToolRegistry,
        clock=None,
        telemetry: Optional[V2Telemetry] = None,
    ) -> None:
        self._registry = NoExecuteToolRegistry(registry)
        self._clock = clock
        self._telemetry = telemetry or V2Telemetry()
        self._builder = GatewayTaskContextBuilder()

    def run_shadow(
        self,
        request: GatewayRequest,
        policy: Optional[ExecutionPolicy] = None,
        step_specs: Optional[List[Dict[str, Any]]] = None,
        timeout: float = 1.0,
    ) -> Dict[str, Any]:
        self._telemetry.record(SHADOW_STARTED, request_id=request.request_id,
                               mode="shadow")
        context = self._builder.build(request)
        # Orchestrator dry_run touches NO store and calls NO tool.
        orchestrator = RuntimeOrchestrator(
            store=None, tool_registry=self._registry,  # type: ignore[arg-type]
            clock=self._clock,
        )
        preview, timed_out, exc = self._dry_run_bounded(
            orchestrator, context, policy, step_specs, timeout
        )
        if timed_out:
            self._telemetry.record(SHADOW_FAILED, request_id=request.request_id,
                                   mode="shadow", reason="timeout")
            logger.warning("gateway.v2.shadow.failed reason=timeout "
                           "request_id=%s", request.request_id)
            return {
                "request_id": request.request_id,
                "mode": "shadow",
                "ok": False,
                "eligible": False,
                "reason": "shadow error: shadow analysis timed out",
                "plan_valid": False,
                "stop_reason": "timeout",
                "timed_out": True,
                "predicted_steps": 0,
                "predicted_tool_calls": 0,
                "would_require_write": False,
                "would_require_approval": False,
                "issues": ["shadow analysis timed out"],
            }
        if exc is not None:
            self._telemetry.record(SHADOW_FAILED, request_id=request.request_id,
                                   mode="shadow", reason=str(exc))
            logger.warning("gateway.v2.shadow.failed request_id=%s error=%s",
                           request.request_id, exc)
            return {
                "request_id": request.request_id,
                "mode": "shadow",
                "ok": False,
                "eligible": False,
                "reason": f"shadow error: {exc}",
                "plan_valid": False,
                "stop_reason": "shadow_error",
                "timed_out": False,
                "predicted_steps": 0,
                "predicted_tool_calls": 0,
                "would_require_write": False,
                "would_require_approval": False,
                "issues": [str(exc)],
            }
        assert preview is not None  # timeout/exception already returned above
        would_require_write = any(
            not self._is_read_only(step["tool"]) for step in preview["steps"]
        )
        would_require_approval = any(
            step["requires_approval"] for step in preview["steps"]
        )
        denied_steps = sum(1 for step in preview["steps"]
                           if step["execution"] == "denied")
        self._telemetry.record(
            SHADOW_COMPLETED, request_id=request.request_id, mode="shadow",
            predicted_steps=preview["predicted_steps"],
            predicted_tool_calls=preview["predicted_tool_calls"],
            would_require_write=would_require_write,
            would_require_approval=would_require_approval,
        )
        logger.info(
            "gateway.v2.shadow.completed request_id=%s predicted_steps=%d "
            "predicted_tools=%d write=%s approval=%s denied=%d",
            request.request_id, preview["predicted_steps"],
            preview["predicted_tool_calls"], would_require_write,
            would_require_approval, denied_steps,
        )
        return {
            "request_id": request.request_id,
            "mode": "shadow",
            "ok": bool(preview["valid"]),
            "eligible": preview["valid"] and not would_require_write,
            "reason": None if preview["valid"] else "; ".join(preview["issues"]),
            "plan_valid": bool(preview["valid"]),
            "stop_reason": "completed" if preview["valid"] else "plan_invalid",
            "timed_out": False,
            "predicted_steps": preview["predicted_steps"],
            "predicted_tool_calls": preview["predicted_tool_calls"],
            "would_require_write": would_require_write,
            "would_require_approval": would_require_approval,
            "denied_steps": denied_steps,
            "issues": preview["issues"],
        }

    # ── internals ────────────────────────────────────────────────────

    @staticmethod
    def _dry_run_bounded(orchestrator, context, policy, step_specs, timeout):
        """dry_run under a hard wall-clock timeout.

        ThreadPoolExecutor WITHOUT the context manager — ``__exit__``
        joins the worker and would defeat the timeout on a hung run
        (proven 1.0.2 pitfall).
        """
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(
                orchestrator.dry_run, context, policy, step_specs
            )
            try:
                return future.result(timeout=timeout), False, None
            except concurrent.futures.TimeoutError:
                return None, True, None
            except Exception as exc:  # shadow must never break the legacy path
                return None, False, exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _is_read_only(self, tool: str) -> bool:
        if not self._registry.has(tool):
            return False  # unknown tool → conservatively a write risk
        return self._registry.metadata(tool).side_effect_class \
            is SideEffectClass.READ_ONLY


__all__ = [
    "ShadowRunner", "NoExecuteToolRegistry", "default_shadow_registry",
]
