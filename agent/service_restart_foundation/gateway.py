"""Sprint 1.3.12 — gateway restart capability.

hermes-gateway: inspect / status / health / eligibility-analysis allowed, but the
restart result is always SELF_CONTROL_FORBIDDEN with execution=0, even if
identity is VERIFIED. The agent must never restart its own gateway.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GatewayRestartResult:
    result: str = "SELF_CONTROL_FORBIDDEN"
    execution: int = 0
    identity_verified: bool = False
    graph_healthy: bool = False


def gateway_restart_capability(
    identity_verified: bool = True,
    graph_healthy: bool = True,
) -> GatewayRestartResult:
    """Gateway restart eligibility analysis — always SELF_CONTROL_FORBIDDEN."""
    # Even when identity_verified and graph_healthy, gateway is self-control.
    return GatewayRestartResult(
        result="SELF_CONTROL_FORBIDDEN",
        execution=0,
        identity_verified=identity_verified,
        graph_healthy=graph_healthy,
    )


def gateway_self_control_forbidden() -> bool:
    """Whether gateway self-restart is forbidden — always True in 1.3.12."""
    return True


__all__ = [
    "GatewayRestartResult",
    "gateway_restart_capability",
    "gateway_self_control_forbidden",
]