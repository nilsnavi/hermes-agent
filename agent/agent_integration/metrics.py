"""Control-plane observability counters (Phase 6 §31).

A tiny, thread-safe, in-memory counter registry for the read-only vertical.
Labels are FIXED (no user/agent values go into label names), so no secrets or
identifiers leak through observability. These are counts only -- data, never
authority.
"""

from __future__ import annotations

import threading


# Fixed known metric names (closed set).
METRIC_NAMES = frozenset(
    {
        "tasks_created",
        "tasks_completed",
        "tasks_failed",
        "tasks_human_review",
        "agent_runs",
        "agent_run_duplicates",
        "route_denials",
        "registry_drift",
        "memory_denials",
        "boundary_denials",
        "message_duplicates",
        "cross_tenant_denials",
    }
)


class MetricsError(ValueError):
    """Raised for an unknown metric name."""


class MetricsRegistry:
    """Fixed-name counter registry (thread-safe increment)."""

    __slots__ = ("_counts", "_lock")

    def __init__(self) -> None:
        self._counts: dict[str, int] = {name: 0 for name in METRIC_NAMES}
        self._lock = threading.Lock()

    def increment(self, name: str, *, by: int = 1) -> int:
        if name not in METRIC_NAMES:
            raise MetricsError(f"unknown metric {name!r}")
        if isinstance(by, bool) or not isinstance(by, int) or by < 0:
            raise MetricsError("by must be a non-negative integer")
        with self._lock:
            self._counts[name] += by
            return self._counts[name]

    def get(self, name: str) -> int:
        if name not in METRIC_NAMES:
            raise MetricsError(f"unknown metric {name!r}")
        with self._lock:
            return self._counts[name]

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def __len__(self) -> int:
        return len(METRIC_NAMES)


__all__ = [
    "METRIC_NAMES",
    "MetricsError",
    "MetricsRegistry",
]