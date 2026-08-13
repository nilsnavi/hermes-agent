"""V2 canary policy + safe registry (Sprint 1.0.6/1.0.6.2).

- :class:`V2CanaryPolicy` — DENY BY DEFAULT. Eligibility requires an
  explicit opt-in (request metadata ``runtime_v2_canary=true``; the
  Sprint 1.0.6 ``runtime_v2=true`` key remains accepted as an alias)
  AND membership in every non-empty allowlist AND (when
  ``read_only_only``) no write tools in the request surface.
- :class:`SafeCanaryToolRegistry` — restricted view of the production
  registry: only READ_ONLY side-effect tools are visible. Any write tool
  is invisible → plan validation fails → ZERO execution. Write tools are
  IMPOSSIBLE in canary by construction.
- :func:`default_canary_registry` — Sprint 1.0.6.2: the production-safe
  READ_ONLY canary tool surface (real local handlers, no external
  endpoints, bounded timeouts) used when the gateway hook has no
  production registry wired.
"""

from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from agent.execution.exceptions import ToolNotAllowed
from agent.execution.registry import SideEffectClass, ToolMetadata, ToolRegistry

from .context_builder import GatewayRequest
from .flags import parse_flag

#: Metadata key a request must explicitly set to become canary-eligible.
CANARY_OPTIN_KEY = "runtime_v2_canary"
#: Sprint 1.0.6 alias (kept for backward compatibility).
CANARY_OPTIN_LEGACY_KEY = "runtime_v2"


class V2CanaryPolicy:
    """Deterministic, explicit-opt-in canary eligibility."""

    def __init__(
        self,
        allowed_users: Optional[List[str]] = None,
        allowed_sessions: Optional[List[str]] = None,
        allowed_request_types: Optional[List[str]] = None,
        read_only_only: bool = True,
        registry: Optional[ToolRegistry] = None,
    ) -> None:
        self._users = frozenset(allowed_users or [])
        self._sessions = frozenset(allowed_sessions or [])
        self._request_types = frozenset(allowed_request_types or [])
        self._read_only_only = read_only_only
        self._registry = registry

    @staticmethod
    def _opt_in(request: GatewayRequest) -> str:
        """Explicit opt-in value: runtime_v2_canary (primary) or the
        Sprint 1.0.6 runtime_v2 alias. Absent → empty string → deny."""
        value = request.metadata.get(
            CANARY_OPTIN_KEY, request.metadata.get(CANARY_OPTIN_LEGACY_KEY)
        )
        return "" if value is None else str(value)

    def is_eligible(self, request: GatewayRequest) -> Tuple[bool, str]:
        """(eligible, reason). Deny by default; never random rollout."""
        if not parse_flag(self._opt_in(request)):
            return False, "no explicit runtime_v2_canary opt-in"
        if not self._users and not self._sessions and not self._request_types:
            return False, "deny_by_default"  # no allowlist configured at all
        if self._users and request.user_id not in self._users:
            return False, "user not allowlisted"
        if self._sessions and request.session_id not in self._sessions:
            return False, "session not allowlisted"
        if self._request_types and request.request_type not in self._request_types:
            return False, "request_type not allowlisted"
        if self._read_only_only and self._requires_write(request):
            return False, "request requires write tools"
        return True, "eligible"

    def _requires_write(self, request: GatewayRequest) -> bool:
        if self._registry is None:
            # Unknown tool surface → treat as possibly-write → ineligible.
            return bool(request.allowed_tools)
        for tool in request.allowed_tools:
            if not self._registry.has(tool):
                return True  # unknown tool → conservatively a write risk
            if self._registry.metadata(tool).side_effect_class \
                    is not SideEffectClass.READ_ONLY:
                return True
        return False

    def summary(self) -> Dict[str, Any]:
        return {
            "allowed_users": sorted(self._users),
            "allowed_sessions": sorted(self._sessions),
            "allowed_request_types": sorted(self._request_types),
            "read_only_only": self._read_only_only,
            "deny_by_default": not self._users and not self._sessions,
        }


def _runtime_status_handler(arguments: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Read the gateway runtime status record — local file read.

    Returns ONLY safe scalar keys (never argv / env / paths). Falls back
    to an empty record when the file is unavailable (e.g. CLI harness).
    """
    try:
        from gateway.status import read_runtime_status

        rec = read_runtime_status() or {}
    except Exception:
        rec = {}
    safe = {k: rec.get(k) for k in
            ("gateway_state", "pid", "start_time", "updated_at", "kind")
            if k in rec}
    return safe or {"gateway_state": "unknown"}


def _canary_ping_handler(arguments: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Pure local probe: no side effects, no external calls."""
    from datetime import datetime, timezone

    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


def default_canary_registry() -> ToolRegistry:
    """Production-safe READ_ONLY canary tool surface (§11-13 audit).

    Real handlers, local-only, no auth/session mutation, no external
    endpoints, predictable responses, bounded timeouts. SafeCanaryTool-
    Registry additionally filters at the canary boundary, so write tools
    remain impossible even if this registry is ever swapped for a wider
    one.
    """
    reg = ToolRegistry()
    reg.register(
        "runtime_status", _runtime_status_handler,
        metadata=ToolMetadata(idempotent=True,
                              side_effect_class=SideEffectClass.READ_ONLY,
                              timeout=2.0),
    )
    reg.register(
        "canary_ping", _canary_ping_handler,
        metadata=ToolMetadata(idempotent=True,
                              side_effect_class=SideEffectClass.READ_ONLY,
                              timeout=2.0),
    )
    return reg


class SafeCanaryToolRegistry:
    """Registry view exposing ONLY tools with an allowed side-effect class.

    ``has(name)`` is False for write tools → PlanValidator reports
    "unknown tool" → the plan is INVALID → zero tools execute. Fail
    closed, by construction.
    """

    def __init__(
        self,
        base: ToolRegistry,
        allowed_classes: FrozenSet[SideEffectClass] = frozenset(
            {SideEffectClass.READ_ONLY}
        ),
    ) -> None:
        self._base = base
        self._allowed = allowed_classes

    def _visible(self, name: str) -> bool:
        return (
            self._base.has(name)
            and self._base.metadata(name).side_effect_class in self._allowed
        )

    def has(self, name: str) -> bool:
        return self._visible(name)

    def is_allowed(self, name: str) -> bool:
        return self._visible(name)

    def metadata(self, name: str) -> ToolMetadata:
        return self._base.metadata(name)

    def get(self, name: str):
        if not self._visible(name):
            raise ToolNotAllowed(name)
        return self._base.get(name)

    def validator(self, name: str):
        return self._base.validator(name) if self._visible(name) else None

    def names(self) -> List[str]:
        return [
            name for name in self._base.names()
            if self._base.metadata(name).side_effect_class in self._allowed
        ]
