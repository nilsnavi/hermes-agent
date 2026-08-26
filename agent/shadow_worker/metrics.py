"""Worker observability metrics (Phase 8.3 §21).

A closed set of fixed metric names with a label-safety rule identical in spirit
to the platform_shadow observability: no secret / PII / tenant text can enter a
label or a metric name.  Metrics are observability only, never authority.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


#: Closed worker metric names (Phase 8.3 §21). No dynamic names.
WORKER_METRIC_NAMES = frozenset(
    {
        "worker_envelopes_received",
        "worker_envelopes_invalid",
        "worker_envelopes_duplicate",
        "worker_runs_started",
        "worker_runs_completed",
        "worker_runs_failed",
        "worker_runs_unknown",
        "worker_memory_denied",
        "worker_boundary_denied",
        "worker_network_denied",
        "worker_duration_ms",
        "worker_queue_depth",
    }
)


class WorkerMetricError(ValueError):
    pass


class WorkerMetrics:
    """Thread-safe fixed counter registry for the isolated worker."""

    __slots__ = ("_counters", "_duration_ms", "_lock", "_started")

    def __init__(self) -> None:
        self._counters: dict[str, int] = {name: 0 for name in WORKER_METRIC_NAMES}
        self._duration_ms = 0.0
        self._lock = threading.Lock()
        self._started = False

    def increment(self, name: str, delta: int = 1) -> None:
        if name not in WORKER_METRIC_NAMES:
            raise WorkerMetricError(f"metric name {name!r} is not in the closed set")
        if not isinstance(delta, int) or delta < 0:
            raise WorkerMetricError("delta must be a non-negative int")
        with self._lock:
            self._counters[name] += delta

    def add_duration(self, ms: float) -> None:
        if not isinstance(ms, (int, float)) or ms < 0:
            raise WorkerMetricError("duration must be a non-negative number")
        with self._lock:
            self._duration_ms += float(ms)

    def set_queue_depth(self, depth: int) -> None:
        if not isinstance(depth, int) or depth < 0:
            raise WorkerMetricError("queue depth must be a non-negative int")
        with self._lock:
            self._counters["worker_queue_depth"] = depth

    def get(self, name: str) -> int:
        if name not in WORKER_METRIC_NAMES:
            raise WorkerMetricError(f"metric name {name!r} is not in the closed set")
        with self._lock:
            return self._counters[name]

    def duration_ms(self) -> float:
        with self._lock:
            return self._duration_ms

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)


@dataclass(frozen=True, slots=True)
class MetricsSummary:
    counts: dict[str, int]
    total_duration_ms: float


__all__ = ["WORKER_METRIC_NAMES", "MetricsSummary", "WorkerMetricError", "WorkerMetrics"]