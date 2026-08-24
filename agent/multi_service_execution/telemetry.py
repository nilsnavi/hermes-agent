"""Sprint 1.3.17 — scalar execution telemetry (whitelist only).

Counters are scalar and must-stay-zero (``real_adapter_calls``,
``real_compensation_adapter_calls``).  Reading never bumps.
"""
from __future__ import annotations

import threading


class ExecutionTelemetry:
    def __init__(self) -> None:
        self._n = {"shadow_evaluations": 0, "rehearsal_evaluations": 0,
                   "denied": 0, "committed_simulated": 0, "unknown_outcome": 0,
                   "compensation_required": 0, "simulated_adapter_calls": 0,
                   "real_adapter_calls": 0, "real_compensation_adapter_calls": 0}
        self._lock = threading.Lock()

    def tick(self, key: str, delta: int = 1) -> None:
        with self._lock:
            self._n[key] = self._n.get(key, 0) + delta

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._n)

    def real_calls(self) -> int:
        with self._lock:
            return self._n["real_adapter_calls"]


__all__ = ["ExecutionTelemetry"]