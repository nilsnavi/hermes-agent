"""Log deduplication (Sprint 0.7 §9).

One identical failure must not write a full log every retry.  First
occurrence → emitted in full; identical repeats → counter; a periodic
summary (or a change of error class) emits a fresh line.

Before (gateway reconnect loop): ~288 identical lines/day for
homeassistant.local DNS.  After: 1 full + counter + sparse summaries.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Tuple


class LogDedup:
    """Thread-safe per-(integration, error_class) suppression."""

    def __init__(self, summary_every: int = 25) -> None:
        self._summary_every = summary_every
        self._lock = threading.Lock()
        # key (integration, error_class) -> [count, first_seen, last_seen]
        self._seen: Dict[Tuple[str, str], list] = {}

    def should_suppress(self, integration: str, error_class: str) -> bool:
        """True → caller may skip the full log line (counter++ only)."""
        key = (integration, error_class)
        with self._lock:
            entry = self._seen.get(key)
            now = time.time()
            if entry is None:
                self._seen[key] = [1, now, now, 0]
                return False
            entry[0] += 1
            entry[2] = now
            if entry[0] % self._summary_every == 0:
                # periodic summary tick — let one line through
                entry[3] += 1
                return False
            return True

    def count(self, integration: str, error_class: str) -> int:
        key = (integration, error_class)
        with self._lock:
            entry = self._seen.get(key)
            return 0 if entry is None else entry[0]

    def should_summary(self, integration: str, error_class: str) -> bool:
        """True only on the periodic window tick (every N repeats).

        Lets callers emit a sparse 'N repeated' event instead of one
        event per suppressed attempt (§9 noise budget).
        """
        key = (integration, error_class)
        with self._lock:
            entry = self._seen.get(key)
            return bool(entry) and entry[0] % self._summary_every == 0

    def summary(self, integration: str, error_class: str) -> str:
        n = self.count(integration, error_class)
        return f"{integration} {error_class} repeated {n} times"