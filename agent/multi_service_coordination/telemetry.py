"""Sprint 1.3.15 — coordination telemetry.

Counters are durable (journal-derived where possible).  Expected invariant:
real_adapter_calls == 0 at all times.
"""
from __future__ import annotations

import time
from pathlib import Path

from agent.service_restart_policy._durable import JsonTransaction


class CoordinatorTelemetry:
    def __init__(self, root: str | Path) -> None:
        self._tx = JsonTransaction(root, "telemetry")

    def _bump(self, key: str) -> int:
        def change(data):
            data[key] = int(data.get(key, 0)) + 1
            return data[key]

        return self._tx.update(change)

    def plans_total(self) -> int:
        return self._bump("plans_total")

    def plans_denied(self) -> int:
        return self._bump("plans_denied")

    def prepare_failures(self) -> int:
        return self._bump("prepare_failures")

    def lock_failures(self) -> int:
        return self._bump("lock_failures")

    def deadlock_avoided(self) -> int:
        return self._bump("deadlock_avoided")

    def duplicate_global_intents(self) -> int:
        return self._bump("duplicate_global_intents")

    def unknown_outcomes(self) -> int:
        return self._bump("unknown_outcomes")

    def compensation_required(self) -> int:
        return self._bump("compensation_required")

    def simulated_commits(self) -> int:
        return self._bump("simulated_commits")

    def real_adapter_calls(self) -> int:
        """Read-only: the count of real adapter calls, always 0 in 1.3.15.

        Bumping is never reachable because execution_guard blocks execution
        outright; this getter must NOT bump (otherwise reading it inflates it).
        """
        return int(self._tx.read().get("real_adapter_calls", 0))

    def snapshot(self) -> dict:
        return self._tx.read()


__all__ = ["CoordinatorTelemetry"]