"""Sprint 1.3.13 — single aux service restart canary (telemetry)."""
from __future__ import annotations

import threading

C_RESTART_SUCCESS = "restart_success"
C_RESTART_ATTEMPTS = "restart_attempts"
C_ADAPTER_CALLS = "actual_restart_adapter_calls"
C_DUPLICATE = "duplicate_restart_execution"
C_STOP_PUBLIC = "stop_public_execution"
C_START_PUBLIC = "start_public_execution"
C_KILL_SIGNAL = "kill_signal_execution"
C_GATEWAY_MUTATION = "gateway_mutation"
C_NON_REGISTERED = "non_registered_restart"
C_UNKNOWN_RETRIES = "unknown_outcome_retries"
C_RESTART_AS_ROLLBACK = "restart_as_rollback"
C_EXECUTION_BLOCKED = "restart_execution_blocked"

_COUNTERS = {k: 0 for k in (
    C_RESTART_SUCCESS, C_RESTART_ATTEMPTS, C_ADAPTER_CALLS, C_DUPLICATE,
    C_STOP_PUBLIC, C_START_PUBLIC, C_KILL_SIGNAL, C_GATEWAY_MUTATION,
    C_NON_REGISTERED, C_UNKNOWN_RETRIES, C_RESTART_AS_ROLLBACK,
    C_EXECUTION_BLOCKED,
)}
_lock = threading.Lock()


def inc(name: str, amount: int = 1) -> None:
    if name not in _COUNTERS:
        raise KeyError(name)
    with _lock:
        _COUNTERS[name] += amount


def get(name: str) -> int:
    with _lock:
        return _COUNTERS[name]


def snapshot() -> dict:
    with _lock:
        return dict(_COUNTERS)


def reset() -> None:
    with _lock:
        for k in _COUNTERS:
            _COUNTERS[k] = 0


__all__ = [
    "C_ADAPTER_CALLS",
    "C_DUPLICATE",
    "C_EXECUTION_BLOCKED",
    "C_GATEWAY_MUTATION",
    "C_KILL_SIGNAL",
    "C_NON_REGISTERED",
    "C_RESTART_AS_ROLLBACK",
    "C_RESTART_ATTEMPTS",
    "C_RESTART_SUCCESS",
    "C_START_PUBLIC",
    "C_STOP_PUBLIC",
    "C_UNKNOWN_RETRIES",
    "get",
    "inc",
    "reset",
    "snapshot",
]