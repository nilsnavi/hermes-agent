"""Sprint 1.3.12 — execution guard (P0).

execute(restart_plan) ALWAYS returns SERVICE_RESTART_DISABLED with
adapter_calls=0, even if eligibility == ELIGIBLE_FOR_FUTURE_RESTART_CANARY.
The guard does not accept raw commands / shell strings / arbitrary units. There
is NO production restart/stop/start adapter in this sprint.
"""
from __future__ import annotations

import threading

# Tokens that must never be an accepted execution surface.
FORBIDDEN_EXEC_TOKENS = (
    "systemctl restart",
    "systemctl stop",
    "systemctl start",
    "service restart",
    "service stop",
    "service start",
    "kill",
    "pkill",
    "signal",
)

_adapter_counter = 0
_lock = threading.Lock()


def adapter_calls() -> int:
    """Number of production adapter calls made — always 0 in 1.3.12."""
    with _lock:
        return _adapter_counter


def accepts_raw_command() -> bool:
    """The guard never accepts a raw command / shell string."""
    return False


def accepts_arbitrary_unit() -> bool:
    """The guard never accepts an arbitrary unit name for restart."""
    return False


def restart_execution_guard(plan_id: str = "", service_id: str = "") -> str:
    """Always-disabled verdict. Counts 0 adapter calls; records nothing mutating."""
    return "SERVICE_RESTART_DISABLED"


def execute_restart(plan_id: str = "", service_id: str = "",
                    eligibility: str | None = None) -> str:
    """Attempt to execute a restart plan -> ALWAYS SERVICE_RESTART_DISABLED.

    Even an ELIGIBLE_FOR_FUTURE_RESTART_CANARY eligibility is not execution
    authority. The adapter is never invoked (adapter_calls stays 0).
    """
    # Eligibility is explicitly ignored: it is not authority.
    _ = eligibility
    return (
        "SERVICE_RESTART_DISABLED eligibility_not_authority "
        f"plan={plan_id} service={service_id} adapter=0"
    )


class _ExecutionGuard:
    """Singleton-style accessor mirroring the module functions (test-friendly)."""

    FORBIDDEN_EXEC_TOKENS = FORBIDDEN_EXEC_TOKENS

    @staticmethod
    def execute(plan_id: str = "", service_id: str = "", **_kw) -> str:
        return execute_restart(plan_id=plan_id, service_id=service_id)

    @staticmethod
    def adapter_calls() -> int:
        return adapter_calls()

    @staticmethod
    def accepts_raw_command() -> bool:
        return False

    @staticmethod
    def accepts_arbitrary_unit() -> bool:
        return False


guard = _ExecutionGuard


__all__ = [
    "FORBIDDEN_EXEC_TOKENS",
    "_ExecutionGuard",
    "accepts_arbitrary_unit",
    "accepts_raw_command",
    "adapter_calls",
    "execute_restart",
    "guard",
    "restart_execution_guard",
]