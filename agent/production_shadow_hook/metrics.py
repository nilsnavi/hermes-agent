"""Live-hook observability (Phase 8 §8, §17).

Fixed-name counter registry with a CLOSED label allowlist so no PII/secret ever
enters a label. Includes the §8 dropped sub-reasons and the §17 hook metrics.
"""

from __future__ import annotations

import threading
import time


class _LabelError(ValueError):
    pass


# Closed set of live-hook metric names.
SHADOW_HOOK_METRIC_NAMES = frozenset(
    {
        "shadow_hook_received",
        "shadow_hook_sampled",
        "shadow_hook_enqueued",
        "shadow_hook_dropped",
        "shadow_hook_dropped_queue_full",
        "shadow_hook_dropped_invalid",
        "shadow_hook_dropped_over_budget",
        "shadow_hook_errors",
        "shadow_hook_latency_ms",
        "shadow_processing_latency_ms",
        "shadow_queue_depth",
        "shadow_comparison_match",
        "shadow_comparison_mismatch",
    }
)

_SAFE_VALUES = frozenset({"local", "canary", "test", "off"})


class ShadowHookMetrics:
    """Thread-safe fixed-counter registry for the live hook (no PII in labels)."""

    __slots__ = ("_counters", "_latency_ms", "_lock")

    def __init__(self) -> None:
        self._counters: dict[str, int] = {n: 0 for n in SHADOW_HOOK_METRIC_NAMES}
        self._latency_ms = 0.0
        self._lock = threading.Lock()

    def increment(self, name: str, delta: int = 1, *, labels: dict[str, str] | None = None) -> None:
        if name not in SHADOW_HOOK_METRIC_NAMES:
            raise _LabelError(f"metric name {name!r} not in the closed set")
        if labels:
            for key, value in labels.items():
                if key not in ("mode", "reason") or value not in _SAFE_VALUES:
                    raise _LabelError("insafe metric label")
        with self._lock:
            self._counters[name] += delta

    def accumulate_latency(self, name: str, ms: float) -> None:
        if name not in ("shadow_hook_latency_ms", "shadow_processing_latency_ms"):
            raise _LabelError(f"latency name {name!r} not supported")
        with self._lock:
            self._latency_ms += float(ms)

    def get(self, name: str) -> int:
        if name not in SHADOW_HOOK_METRIC_NAMES:
            raise _LabelError(f"metric name {name!r} not in the closed set")
        with self._lock:
            return self._counters.get(name, 0)

    def latency_ms(self) -> float:
        with self._lock:
            return self._latency_ms

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)


# Fixed transport label used by tests/harness (safe, enum-like).
LOCAL_TRANSPORT = "local"

__all__ = ["LOCAL_TRANSPORT", "SHADOW_HOOK_METRIC_NAMES", "ShadowHookMetrics"]