"""Tool adapters (Sprint 1.3.2 §10, §27).

Canonical adapter interface:

    VerifiedToolAdapter.execute(context, arguments) -> AdapterResult

Adapters do NOT know about routing and do NOT make policy decisions —
they execute the approved tool and report the observed side effect.
The executor validates everything else.

Migrated tools (Sprint 1.3.2 §27 — only production-approved V2 tools):

    STATUS_READ tool set: runtime_status / gateway_status /
        integration_status / scheduler_status / provider_status
    operational_log_search

No new tools. The default adapters below wrap the EXISTING verified
implementations (the Sprint 1.0.6 canary handlers in
``agent.gateway_v2.canary``) so behavior stays byte-identical
(§28/§29 equivalence). The wrap uses lazy import INSIDE execute() —
the executor package itself stays importable standalone, and a missing
legacy handler can never break the contract layer.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol, runtime_checkable

from .models import ExecutionContext, SideEffectReport


@dataclass(frozen=True)
class AdapterResult:
    """One adapter outcome: output + observed side effect (§34)."""

    output: Optional[Dict[str, Any]]
    observed_side_effect: str = SideEffectReport.READ_ONLY.value
    error_class: Optional[str] = None
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output": self.output,
            "observed_side_effect": self.observed_side_effect,
            "error_class": self.error_class,
            "error_code": self.error_code,
        }


@runtime_checkable
class VerifiedToolAdapter(Protocol):
    """§10 — canonical adapter contract."""

    def execute(
        self,
        context: ExecutionContext,
        arguments: Dict[str, Any],
    ) -> AdapterResult:
        ...


class HandlerAdapter:
    """Wrap a legacy handler ``fn(arguments, context_dict) -> dict``.

    The context dict handed to the handler carries only bounded safe
    values (goal text from the whitelisted metadata — never the raw
    prompt). Side effect is reported READ_ONLY (all migrated tools
    are verified READ_ONLY).
    """

    def __init__(
        self,
        handler: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
    ) -> None:
        self._handler = handler

    def execute(
        self,
        context: ExecutionContext,
        arguments: Dict[str, Any],
    ) -> AdapterResult:
        goal = context.goal or ""
        try:
            output = self._handler(arguments, {"goal": goal})
        except Exception as exc:  # normalized by the executor
            return AdapterResult(
                output=None,
                observed_side_effect=SideEffectReport.UNKNOWN.value,
                error_class=type(exc).__name__,
                error_code="TOOL_EXECUTION_ERROR",
            )
        if not isinstance(output, dict):
            return AdapterResult(
                output=output if isinstance(output, dict) else None,
                observed_side_effect=SideEffectReport.UNKNOWN.value,
                error_class="INVALID_TOOL_RESULT",
                error_code="INVALID_TOOL_RESULT",
            )
        return AdapterResult(
            output=output,
            observed_side_effect=SideEffectReport.READ_ONLY.value,
        )


def context_goal(context: ExecutionContext) -> str:
    """Bounded goal text (search query fallback) from the context.

    The goal is a bounded (≤500 chars) router-validated value carried
    on the ExecutionContext — NOT the raw prompt (§12). It feeds the
    operational search handler's ``context.goal`` fallback exactly as
    the legacy canary path does, keeping behavior identical.
    """
    return getattr(context, "goal", "") or ""


# ── default migrated adapters (lazy-import the existing handlers) ──

def _canary_handler(tool_name: str):
    """Lazy-import the Sprint 1.0.6 canary handler for *tool_name*."""
    from agent.gateway_v2.canary import default_canary_registry

    registry = default_canary_registry()
    handler = registry.get(tool_name)
    if handler is None:
        raise LookupError(f"canary handler not found: {tool_name}")
    return handler


def default_adapter(tool_name: str) -> HandlerAdapter:
    """Adapter over the existing verified handler for *tool_name*.

    Only production-approved tools are allowed (§27); anything else
    raises (the registry rejects it before execution anyway).
    """
    return HandlerAdapter(_canary_handler(tool_name))


def default_adapters() -> Dict[str, HandlerAdapter]:
    """Adapters for the full migrated tool surface (§27)."""
    return {
        name: default_adapter(name)
        for name in (
            "runtime_status",
            "gateway_status",
            "integration_status",
            "scheduler_status",
            "provider_status",
            "operational_log_search",
        )
    }


# ── explicit argument schemas (§8 — every tool has one) ─────────────

#: Search tool argument schema — bounded, closed enums only.
SEARCH_ARGUMENT_SCHEMA: Dict[str, Any] = {
    "fields": {
        "query": {"type": "str", "required": False, "max_len": 500},
        "source": {"type": "str", "required": False, "allowed": [
            "GATEWAY_LOG", "EVENTS", "SCHEDULER", "PROVIDER",
            "INTEGRATION",
        ]},
        "time_window": {"type": "str", "required": False, "allowed": [
            "15m", "1h", "6h", "24h",
        ]},
        "limit": {"type": "int", "required": False, "min": 1, "max": 50},
    },
}

#: STATUS_READ tools take no arguments.
EMPTY_SCHEMA: Dict[str, Any] = {"fields": {}}

#: Per-tool argument schemas for the migrated surface.
DEFAULT_ARGUMENT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "runtime_status": EMPTY_SCHEMA,
    "gateway_status": EMPTY_SCHEMA,
    "integration_status": EMPTY_SCHEMA,
    "scheduler_status": EMPTY_SCHEMA,
    "provider_status": EMPTY_SCHEMA,
    "operational_log_search": SEARCH_ARGUMENT_SCHEMA,
}


def default_argument_schemas() -> Dict[str, Dict[str, Any]]:
    return dict(DEFAULT_ARGUMENT_SCHEMAS)


def bind_default_adapters(registry) -> None:
    """Bind the default migrated adapters WITH their explicit argument
    schemas onto a VerifiedToolRegistry (§27/§8)."""
    from .registry import EMPTY_ARGUMENT_SCHEMA

    adapters = default_adapters()
    schemas = default_argument_schemas()
    for tool, adapter in adapters.items():
        registry.bind(
            tool, adapter,
            argument_schema=schemas.get(tool, EMPTY_ARGUMENT_SCHEMA))


__all__ = [
    "AdapterResult",
    "VerifiedToolAdapter",
    "HandlerAdapter",
    "default_adapter",
    "default_adapters",
    "default_argument_schemas",
    "bind_default_adapters",
    "SEARCH_ARGUMENT_SCHEMA",
    "DEFAULT_ARGUMENT_SCHEMAS",
]
