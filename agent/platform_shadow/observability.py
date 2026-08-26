"""Shadow observability: bounded metrics + correlation-only tracing (Phase 7 §11, §12).

Metrics names are FIXED and closed. Label VALUES must never contain raw user
text, secrets, emails, tokens or full prompts: labels are restricted to a safe
fixed alphabet and the metric name is whitelisted. Trace ids are correlation
ONLY -- they are never authority and never route to production.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


class _LabelError(ValueError):
    pass


# Closed set of shadow metric names (Phase 7 §11). No dynamic names allowed.
SHADOW_METRIC_NAMES = frozenset(
    {
        "shadow_tasks_received",
        "shadow_tasks_sampled",
        "shadow_tasks_completed",
        "shadow_tasks_failed",
        "shadow_tasks_unknown",
        "shadow_human_review",
        "shadow_route_denied",
        "shadow_policy_denied",
        "shadow_boundary_denied",
        "shadow_memory_denied",
        "shadow_registry_drift",
        "shadow_duplicate_runs",
        "shadow_duration_ms",
        "shadow_agent_selected",
        "shadow_comparison_match",
        "shadow_comparison_mismatch",
    }
)

# Labels with VALUES that are closed enum-ish (safe fixed identifiers). Any other
# label, or a value carrying user-text/secrets, is REJECTED to bound cardinality.
_SAFE_VALUE_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789_-"
_ALLOWED_LABELS = frozenset({"agent_id", "mode", "class"})

# CLOSED value allowlists per label: only these fixed identifiers are acceptable,
# so a secret/email/token/prompt can never be smuggled into a label.
_SAFE_LABEL_VALUES: dict[str, frozenset[str]] = {
    "agent_id": frozenset(
        {"planner", "research", "coding", "reviewer", "memory", "monitoring"}
    ),
    "mode": frozenset({"off", "sample", "full_shadow"}),
    "class": frozenset(
        {
            "match", "partial_match", "different_agent", "different_plan",
            "different_disposition", "shadow_denied", "shadow_unknown", "not_comparable",
        }
    ),
}


def _safe_label(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise _LabelError(f"label must be a string, got {type(value).__name__}")
    allowed = _SAFE_LABEL_VALUES.get(name)
    if allowed is None:
        raise _LabelError(f"label {name!r} has no closed value allowlist")
    if value not in allowed:
        # Reject anything that is not a fixed enum-like identifier (this blocks
        # emails, tokens, prompts and any user-controlled text).
        raise _LabelError(f"label {name!r} value is not a closed fixed identifier")
    if not all(ch in _SAFE_VALUE_ALPHABET for ch in value) or len(value) > 32:
        raise _LabelError("label value is not a safe fixed identifier")
    return value


def _check_label(name: str, labels: dict[str, str] | None) -> None:
    if not labels:
        return
    bad = set(labels) - _ALLOWED_LABELS
    if bad:
        raise _LabelError(f"unknown metric label(s): {sorted(bad)}")
    for key, value in labels.items():
        _safe_label(key, value)


class ShadowMetrics:
    """Thread-safe fixed-counter registry for the shadow runtime (no secrets in labels)."""

    __slots__ = ("_counters", "_duration_ms", "_lock", "_started_at")

    def __init__(self) -> None:
        self._counters: dict[str, int] = {name: 0 for name in SHADOW_METRIC_NAMES}
        self._duration_ms = 0.0
        self._lock = threading.Lock()
        self._started_at = time.monotonic()

    def increment(self, name: str, delta: int = 1, *, labels: dict[str, str] | None = None) -> None:
        if name not in SHADOW_METRIC_NAMES:
            raise _LabelError(f"metric name {name!r} is not in the closed set")
        _check_label(name, labels)
        with self._lock:
            self._counters[name] += delta

    def gauge(self, name: str, value: float) -> None:
        """Accumulate the shadow_duration_ms gauge (fixed name, no per-request labels)."""
        if name != "shadow_duration_ms":
            raise _LabelError(f"gauge name {name!r} is not supported")
        with self._lock:
            self._duration_ms += float(value)

    def get(self, name: str) -> int:
        if name not in SHADOW_METRIC_NAMES:
            raise _LabelError(f"metric name {name!r} is not in the closed set")
        with self._lock:
            return self._counters.get(name, 0)

    def duration_ms(self) -> float:
        with self._lock:
            return self._duration_ms

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)


@dataclass(frozen=True, slots=True)
class ShadowSpan:
    """One correlation-only trace step (ids are not authority)."""

    kind: str
    node_id: str
    parent_id: str = ""
    note: str = ""


class ShadowTracer:
    """Builds a correlation chain only; no production coupling, no authority."""

    __slots__ = ("_spans", "_started_at")

    def __init__(self) -> None:
        self._spans: list[ShadowSpan] = []
        self._started_at = time.monotonic()

    def record(self, kind: str, node_id: str, parent_id: str = "", note: str = "") -> None:
        self._spans.append(ShadowSpan(kind, node_id, parent_id, note))

    def chain(self) -> tuple[str, ...]:
        """Return the ordered correlation-id chain."""
        return tuple(span.node_id for span in self._spans)

    def kinds(self) -> tuple[str, ...]:
        return tuple(span.kind for span in self._spans)

    def snapshot(self) -> tuple[ShadowSpan, ...]:
        return tuple(self._spans)

    def reset(self, *, retain_clock: bool = True) -> None:  # pragma: no cover - helper
        self._spans = []


__all__ = [
    "SHADOW_METRIC_NAMES",
    "ShadowMetrics",
    "ShadowSpan",
    "ShadowTracer",
]