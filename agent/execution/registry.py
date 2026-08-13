"""Tool registry — the execution allowlist (Sprint 1.0.2 / 1.0.5).

Only tools registered here can be executed; unknown names raise
ToolNotAllowed (fail closed). Handlers are plain callables
``fn(arguments: dict, context: dict) -> dict``; an optional *validator*
runs before execution. Since Sprint 1.0.5 each tool also carries
:class:`ToolMetadata` (idempotency, side-effect class, approval policy,
timeout) consumed by the orchestrator's risk/retry decisions. Default
metadata is maximally conservative: NOT idempotent, side-effect class
UNKNOWN, no approval flag.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .exceptions import ToolNotAllowed

Handler = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
Validator = Callable[[Dict[str, Any]], None]


class SideEffectClass(Enum):
    """Effect a tool call has on the outside world (Sprint 1.0.5).

    Drives the auto-retry policy: READ_ONLY may retry when idempotent;
    REVERSIBLE_WRITE only with an idempotency key; IRREVERSIBLE_WRITE and
    UNKNOWN are NEVER auto-retried.
    """

    READ_ONLY = "read_only"
    REVERSIBLE_WRITE = "reversible_write"
    IRREVERSIBLE_WRITE = "irreversible_write"
    UNKNOWN = "unknown"


@dataclass
class ToolMetadata:
    """Declarative tool policy (Sprint 1.0.5)."""

    idempotent: bool = False
    side_effect_class: SideEffectClass = SideEffectClass.UNKNOWN
    requires_approval: bool = False
    timeout: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Handler] = {}
        self._validators: Dict[str, Validator] = {}
        self._metadata: Dict[str, ToolMetadata] = {}

    def register(
        self,
        name: str,
        handler: Handler,
        validator: Optional[Validator] = None,
        metadata: Optional[ToolMetadata] = None,
    ) -> None:
        """Register *handler* under *name* (re-registration replaces).

        *metadata* declares idempotency / side-effect class / approval
        policy / timeout; absent metadata defaults to conservative.
        """
        if not name or not callable(handler):
            raise ValueError("tool name and callable handler are required")
        self._tools[name] = handler
        if validator is not None:
            self._validators[name] = validator
        if metadata is not None:
            self._metadata[name] = metadata

    def get(self, name: str) -> Handler:
        """Return the handler or raise ToolNotAllowed (allowlist check)."""
        handler = self._tools.get(name)
        if handler is None:
            raise ToolNotAllowed(name)
        return handler

    def validator(self, name: str) -> Optional[Validator]:
        return self._validators.get(name)

    def metadata(self, name: str) -> ToolMetadata:
        """Metadata for *name*; conservative default when undeclared."""
        return self._metadata.get(name, ToolMetadata())

    def has(self, name: str) -> bool:
        return name in self._tools

    def is_allowed(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> List[str]:
        return sorted(self._tools)
