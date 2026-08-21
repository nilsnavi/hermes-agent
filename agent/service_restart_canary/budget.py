"""Sprint 1.3.13 — single aux service restart canary (budget).

SEPARATE from the reload budget. For 1.3.13: max_success=1, max_attempts=2.
After a success the budget prevents any further live restart.
"""
from __future__ import annotations

import threading

MAX_SUCCESSFUL_RESTARTS = 1
MAX_TOTAL_RESTART_ATTEMPTS = 2


class RestartBudget:
    def __init__(self) -> None:
        self._attempts = 0
        self._successes = 0
        self._lock = threading.Lock()

    def remaining_attempts(self) -> int:
        with self._lock:
            return max(0, MAX_TOTAL_RESTART_ATTEMPTS - self._attempts)

    def remaining_successes(self) -> int:
        with self._lock:
            return max(0, MAX_SUCCESSFUL_RESTARTS - self._successes)

    def allow_attempt(self) -> bool:
        """Reserve an attempt budget slot (2 total)."""
        with self._lock:
            if self._attempts >= MAX_TOTAL_RESTART_ATTEMPTS:
                return False
            self._attempts += 1
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._successes < MAX_SUCCESSFUL_RESTARTS:
                self._successes += 1

    def attempts(self) -> int:
        with self._lock:
            return self._attempts

    def successes(self) -> int:
        with self._lock:
            return self._successes


__all__ = [
    "MAX_SUCCESSFUL_RESTARTS",
    "MAX_TOTAL_RESTART_ATTEMPTS",
    "RestartBudget",
]