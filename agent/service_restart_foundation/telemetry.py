"""Sprint 1.3.12 — restart foundation telemetry counters.

No high-cardinality raw IDs are exposed; only bounded counters.
"""
from __future__ import annotations

import threading

# Stable counter names.
C_REQUESTED = "service_restart_foundation_requests"
C_ELIGIBLE_FUTURE_CANARY = "service_restart_eligible_future_canary"
C_DENIED = "service_restart_denied"
C_ORPHAN_RISK = "service_restart_orphan_risk"
C_QUIESCENCE_FAIL = "service_restart_quiescence_fail"
C_IDENTITY_DRIFT = "service_restart_identity_drift"
C_GRAPH_DRIFT = "service_restart_graph_drift"
C_EXECUTION_BLOCKED = "service_restart_execution_blocked"

_COUNTERS = {
    C_REQUESTED: 0,
    C_ELIGIBLE_FUTURE_CANARY: 0,
    C_DENIED: 0,
    C_ORPHAN_RISK: 0,
    C_QUIESCENCE_FAIL: 0,
    C_IDENTITY_DRIFT: 0,
    C_GRAPH_DRIFT: 0,
    C_EXECUTION_BLOCKED: 0,
}
_lock = threading.Lock()


def inc(name: str, amount: int = 1) -> None:
    if name not in _COUNTERS:
        raise KeyError(f"unknown counter: {name}")
    with _lock:
        _COUNTERS[name] += amount


def get(name: str) -> int:
    with _lock:
        return _COUNTERS[name]


def snapshot() -> dict[str, int]:
    with _lock:
        return dict(_COUNTERS)


def reset() -> None:
    with _lock:
        for k in _COUNTERS:
            _COUNTERS[k] = 0


__all__ = [
    "C_DENIED",
    "C_ELIGIBLE_FUTURE_CANARY",
    "C_EXECUTION_BLOCKED",
    "C_GRAPH_DRIFT",
    "C_IDENTITY_DRIFT",
    "C_ORPHAN_RISK",
    "C_QUIESCENCE_FAIL",
    "C_REQUESTED",
    "get",
    "inc",
    "reset",
    "snapshot",
]