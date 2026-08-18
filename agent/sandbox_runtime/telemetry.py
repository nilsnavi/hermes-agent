"""Sandbox telemetry counters (Sprint 1.3.5 §30)."""

from __future__ import annotations

import threading
import time
from typing import Dict

#: Canonical counter names.
COUNTERS = (
    "sandbox_mutation_attempts",
    "sandbox_mutation_committed",
    "sandbox_mutation_failed",
    "sandbox_mutation_rollback",
    "sandbox_mutation_rollback_failed",
    "sandbox_unknown_outcome",
    "sandbox_duplicate_action",
    "sandbox_preflight_failed",
    "sandbox_boundary_blocked",
    "sandbox_toctou_blocked",
    "sandbox_path_escape_blocked",
    "sandbox_lock_conflict",
    "sandbox_approval_denied",
    "sandbox_recovery_scans",
    "sandbox_recovery_incomplete",
    "sandbox_manual_review_created",
    "sandbox_reconciliation_unknown",
    "sandbox_snapshot_corrupt",
    "sandbox_lock_state_ambiguous",
    "sandbox_chaos_injected",
    # Sprint 1.3.6 canonical names (no raw-ID labels).
    "sandbox_incomplete_transactions",
    "sandbox_unknown_outcomes",
    "sandbox_recovered_transactions",
    "sandbox_manual_reviews",
    "sandbox_stale_locks",
    "sandbox_lock_recoveries",
    "sandbox_snapshot_corruptions",
    "sandbox_rollback_failures",
    "sandbox_crash_recoveries",
)

#: Latency buckets (ms) — p95 computed from samples.
LATENCY_BUCKETS = ("preflight", "backup", "execution", "verification",
                   "rollback", "total_transaction")


class Telemetry:
    """Thread-safe counters + latency samples (append-only)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {c: 0 for c in COUNTERS}
        self._latency: Dict[str, list] = {b: [] for b in LATENCY_BUCKETS}

    def inc(self, counter: str, delta: int = 1) -> None:
        with self._lock:
            if counter in self._counters:
                self._counters[counter] += delta

    def record_latency(self, bucket: str, seconds: float) -> None:
        with self._lock:
            if bucket in self._latency:
                self._latency[bucket].append(seconds * 1000.0)

    def counters(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def p95(self, bucket: str) -> float:
        with self._lock:
            samples = sorted(self._latency.get(bucket, []))
        if not samples:
            return 0.0
        idx = max(0, int(0.95 * len(samples)) - 1)
        return samples[idx]

    def summary(self) -> Dict:
        return {
            "counters": self.counters(),
            "latency_p95_ms": {
                b: self.p95(b) for b in LATENCY_BUCKETS},
        }


class Timing:
    """Context-manager timer helper for latency buckets."""

    def __init__(self, telemetry: Telemetry, bucket: str) -> None:
        self._t = telemetry
        self._bucket = bucket
        self._start = time.monotonic()

    def __enter__(self) -> "Timing":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.done()

    def done(self) -> float:
        elapsed = time.monotonic() - self._start
        self._t.record_latency(self._bucket, elapsed)
        return elapsed
