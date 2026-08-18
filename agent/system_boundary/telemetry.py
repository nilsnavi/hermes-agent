"""SBL telemetry (Sprint 1.3.3 §51).

Bounded-label counters. Raw path labels are never used. This module
provides a deterministic in-process counter registry (no external
dependency) — the executor/gateway can bridge it to its metrics
exporter.
"""

import threading
from typing import Dict, Optional

_lock = threading.Lock()
_counters: Dict[str, int] = {}


def inc(name: str, amount: int = 1) -> None:
    with _lock:
        _counters[name] = _counters.get(name, 0) + amount


def get(name: str) -> int:
    with _lock:
        return _counters.get(name, 0)


def snapshot() -> Dict[str, int]:
    with _lock:
        return dict(_counters)


def reset() -> None:
    with _lock:
        _counters.clear()


#: canonical metric names (§51)
METRICS = {
    "sbl_requests_total",
    "sbl_pass_total",
    "sbl_block_total",
    "sbl_revalidate_total",
    "sbl_risk_escalations_total",
    "sbl_preflight_created_total",
    "sbl_preflight_expired_total",
    "sbl_preflight_mismatch_total",
    "sbl_toctou_detected_total",
    "sbl_boundary_bypass_total",
    "sbl_self_control_block_total",
    "sbl_dependency_unknown_total",
    "sbl_graph_refresh_total",
    "sbl_graph_refresh_failures_total",
    "sbl_graph_health",
}


__all__ = ["inc", "get", "snapshot", "reset", "METRICS"]
