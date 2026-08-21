"""Sprint 1.3.13 — single aux service restart canary (gateway deny, P0).

hermes-gateway: restart/reload/stop/start/kill/signal -> SELF_CONTROL_FORBIDDEN.
adapter=0. The agent never mutates its own gateway process.
"""
from __future__ import annotations

from dataclasses import dataclass

FORBIDDEN_GATEWAY_OPS = ("restart", "reload", "stop", "start", "kill", "signal")


@dataclass(frozen=True)
class GatewayGuardResult:
    result: str = "SELF_CONTROL_FORBIDDEN"
    execution: int = 0
    op: str = "restart"


def gateway_self_control(op: str = "restart") -> GatewayGuardResult:
    """Any gateway mutation op is forbidden; adapter=0 always."""
    op = (op or "restart").lower()
    if op not in FORBIDDEN_GATEWAY_OPS:
        op = "restart"
    return GatewayGuardResult(result="SELF_CONTROL_FORBIDDEN", execution=0, op=op)


__all__ = ["FORBIDDEN_GATEWAY_OPS", "GatewayGuardResult", "gateway_self_control"]