"""Sprint 1.3.12 — restart mutation budget foundation.

Restart has a SEPARATE budget; it never auto-reuses the reload counter.
Planned future shape: max restart success = 1/hour/service, attempts = 2/hour/
service. In 1.3.12 production usage is 0 — the budget only records shadow
readiness, never authorizes real mutations.
"""
from __future__ import annotations

import threading
import time

MAX_SUCCESS_PER_HOUR = 1
MAX_ATTEMPTS_PER_HOUR = 2


class RestartBudget:
    def __init__(self) -> None:
        self._attempts: list[float] = []
        self._successes: list[float] = []
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        horizon = now - 3600.0
        self._attempts = [t for t in self._attempts if t >= horizon]
        self._successes = [t for t in self._successes if t >= horizon]

    def remaining_attempts(self, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        with self._lock:
            self._prune(now)
            return max(0, MAX_ATTEMPTS_PER_HOUR - len(self._attempts))

    def remaining_successes(self, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        with self._lock:
            self._prune(now)
            return max(0, MAX_SUCCESS_PER_HOUR - len(self._successes))

    def record_attempt(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self._lock:
            self._prune(now)
            self._attempts.append(now)

    def record_success(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self._lock:
            self._prune(now)
            self._successes.append(now)

    def production_usage(self) -> int:
        """Real production mutations recorded against this budget — always 0."""
        return 0


__all__ = [
    "MAX_ATTEMPTS_PER_HOUR",
    "MAX_SUCCESS_PER_HOUR",
    "RestartBudget",
]