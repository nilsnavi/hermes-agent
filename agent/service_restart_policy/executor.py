"""Capability-private, non-authoritative restart adapter primitive."""
from __future__ import annotations

import subprocess
from collections.abc import Callable

from .models import ExecutionResult, RestartExecutionRequest
from .registry import RestartProfileRegistry

_GATEWAY_IDS = {"hermes-gateway", "hermes-gateway.service", "gateway"}


class BoundedRestartExecutor:
    """Low-level adapter. It cannot mint authority or commit a transaction."""

    def __init__(
        self,
        registry: RestartProfileRegistry,
        *,
        runner: Callable = subprocess.run,
        rollout_enabled: bool = False,
        kill_switch: bool = True,
        timeout: float = 10.0,
        max_output: int = 4096,
        _runtime_owner: object | None = None,
    ) -> None:
        self.registry = registry
        self.runner = runner
        self.rollout_enabled = rollout_enabled
        self.kill_switch = kill_switch
        self.timeout = timeout
        self.max_output = max(0, max_output)
        self.calls = 0
        self.__runtime_owner = _runtime_owner

    def execute(
        self,
        request: RestartExecutionRequest,
        grant: object | None = None,
    ) -> ExecutionResult:
        if type(self.registry) is not RestartProfileRegistry:
            return ExecutionResult("INVALID_REGISTRY")
        if not isinstance(request, RestartExecutionRequest) or not request.transaction_id:
            return ExecutionResult("INVALID_REQUEST")
        if request.service_id in _GATEWAY_IDS:
            return ExecutionResult("SELF_CONTROL_FORBIDDEN")
        profile = self.registry.resolve(request.service_id)
        if profile is None:
            return ExecutionResult("NOT_REGISTERED")
        if not self.registry.is_exact_profile(profile):
            return ExecutionResult("INVALID_REGISTRY")
        if profile.profile_version != request.profile_version:
            return ExecutionResult("PROFILE_VERSION_MISMATCH")
        if self.kill_switch:
            return ExecutionResult("KILL_SWITCH_ACTIVE")
        if not self.rollout_enabled:
            return ExecutionResult("ROLLOUT_DISABLED")

        # Dynamic import avoids a module cycle while requiring the exact coordinator type.
        from .runtime import LimitedRestartRuntime

        if type(self.__runtime_owner) is not LimitedRestartRuntime:
            return ExecutionResult("EXECUTION_AUTHORITY_MISSING")
        authority = self.__runtime_owner._consume_execution_grant(
            grant, request, profile.unit_name, self
        )
        if authority != "AUTHORIZED":
            return ExecutionResult(authority)

        argv = ["systemctl", "--user", "restart", profile.unit_name]
        try:
            completed = self.runner(
                argv, shell=False, timeout=self.timeout, capture_output=True, text=True,
            )
            self.calls += 1
        except subprocess.TimeoutExpired as exc:
            self.calls += 1
            return ExecutionResult(
                "ADAPTER_UNKNOWN_OUTCOME",
                self.calls,
                stdout=str(exc.stdout or "")[: self.max_output],
                stderr=str(exc.stderr or "")[: self.max_output],
            )
        except Exception as exc:
            self.calls += 1
            return ExecutionResult(
                "ADAPTER_UNKNOWN_OUTCOME", self.calls, stderr=str(exc)[: self.max_output]
            )
        stdout = str(getattr(completed, "stdout", "") or "")[: self.max_output]
        stderr = str(getattr(completed, "stderr", "") or "")[: self.max_output]
        rc = int(getattr(completed, "returncode", -1))
        outcome = "ADAPTER_SUCCEEDED" if rc == 0 else "ADAPTER_FAILED"
        return ExecutionResult(outcome, self.calls, rc, stdout, stderr)


def public_operation(service_id: str, operation: str) -> ExecutionResult:
    if service_id in _GATEWAY_IDS:
        return ExecutionResult("SELF_CONTROL_FORBIDDEN")
    if operation != "RESTART":
        return ExecutionResult("OPERATION_DENIED")
    return ExecutionResult("ROLLOUT_DISABLED")


__all__ = ["public_operation"]
