"""Mandatory pipeline ports (Protocol seams).

The only admissible execution path is:

    AgentCapabilityIntent
      -> platform_policy (PolicyEvaluator)
      -> capability_router (CapabilityRouterSeam)
      -> SystemBoundary (SystemBoundarySeam)
      -> VerifiedToolExecutor (ToolExecutorSeam)
      -> SandboxAdapter (SandboxAdapterSeam)

Each stage is REQUIRED: the security gate refuses admission (DENY /
COMPONENT_MISSING) if any port is absent, unconfigured, or raises. There is
deliberately NO optional boundary and NO alternative route inside the control
plane. These are typed ports bound at composition time; this module imports no
execution-kernel code and exposes no execution call site.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .status import SideEffectClass


@runtime_checkable
class PolicyEvaluator(Protocol):
    """platform_policy deny-by-default seam: returns an allowance verdict."""

    def evaluate(self, request: Any) -> Any: ...


@runtime_checkable
class CapabilityRouterSeam(Protocol):
    """capability_router seam: maps capability to a policy route/verdict."""

    def decide(self, request: Any) -> Any: ...


@runtime_checkable
class SystemBoundarySeam(Protocol):
    """Mandatory SystemBoundary: preflight + authorize + verify-before/after."""

    def preflight(self, request: Any) -> Any: ...

    def authorize(self, request: Any) -> Any: ...

    def verify_before_execute(self, request: Any) -> Any: ...

    def verify_after_execute(self, request: Any) -> Any: ...


@runtime_checkable
class ToolExecutorSeam(Protocol):
    """VerifiedToolExecutor seam: mandatory, receipt-tracked execution boundary."""

    def is_ready(self) -> bool: ...

    def execute(self, request: Any) -> Any: ...


@runtime_checkable
class SandboxAdapterSeam(Protocol):
    """Sandbox adapter seam: runtime-owned and sealed (never caller-supplied)."""

    def run(self, payload: Any) -> Any: ...


# The ordered mandatory chain, for explicit composition checks.
MANDATORY_PORT_NAMES: tuple[str, ...] = (
    "policy",
    "capability_router",
    "system_boundary",
    "executor",
    "sandbox",
)


def side_effect_of_operation(operation: str) -> SideEffectClass:
    """Classify an operation into a SideEffectClass (single deterministic map).

    This is a pure classification header used by the gate; it performs no
    execution and authorizes nothing.
    """
    if not isinstance(operation, str) or not operation.strip():
        return SideEffectClass.UNKNOWN
    op = operation.strip().lower()
    if op.startswith(("read_", "inspect_", "analyze_", "search_", "get_", "list_")):
        return SideEffectClass.READ_ONLY
    if op in ("shell", "subprocess", "run", "execute", "eval", "exec",
              "execute_code", "run_shell"):
        return SideEffectClass.EXECUTE
    if op in ("write", "write_file", "write_files", "create", "delete", "mv",
              "cp", "patch", "install_dependency", "git_commit", "git_push"):
        return SideEffectClass.WRITE
    if op in ("systemctl", "service", "restart", "reload", "daemon-reload",
              "service_control"):
        return SideEffectClass.SERVICE_MUTATION
    if op in ("system_control", "kernel", "boot", "shutdown"):
        return SideEffectClass.SYSTEM_CONTROL
    if op in ("network", "http", "fetch", "scrape", "request"):
        return SideEffectClass.NETWORK
    return SideEffectClass.UNKNOWN


__all__ = [
    "MANDATORY_PORT_NAMES",
    "CapabilityRouterSeam",
    "PolicyEvaluator",
    "SandboxAdapterSeam",
    "SystemBoundarySeam",
    "ToolExecutorSeam",
    "side_effect_of_operation",
]