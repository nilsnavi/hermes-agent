"""Sprint 1.3.17 — deterministic FakeServiceAdapter (rehearsal/shadow only).

There is NO production adapter in this package.  The fake adapter simulates a
child operation's effect and records a durable per-execution call count.  The
counter is a READ-ONLY getter plus a separate bump() so a must-stay-zero
assertion can't be inflated by reading it (1.3.15 pitfall).

Outcomes are scripted per (execution_id, service_id) so shadow/rehearsal
harnesses can build exact expected matrices.
"""
from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass

from .models import AdapterOutcome


@dataclass(frozen=True, slots=True)
class FakeAdapterResult:
    outcome: AdapterOutcome
    effect: str = ""
    error: str = ""


class FakeServiceAdapter:
    """Deterministic, test-only adapter.  Never calls a real service."""

    def __init__(self) -> None:
        self._calls: dict[str, int] = {}
        self._lock = threading.Lock()

    # -- read-only counter (never bumps) --------------------------------------
    def calls(self, key: str | None = None) -> int:
        with self._lock:
            if key is None:
                return sum(self._calls.values())
            return self._calls.get(key, 0)

    def _record_and_return(self, key: str, result: FakeAdapterResult) -> FakeAdapterResult:
        with self._lock:
            self._calls[key] = self._calls.get(key, 0) + 1
        return result

    def execute(self, key: str, scenario: Mapping[str, str] | None = None) -> FakeAdapterResult:
        """Simulate a single child operation.  ``scenario`` selects the outcome.

        map: {"outcome": "ADAPTER_SUCCEEDED|ADAPTER_FAILED|ADAPTER_UNKNOWN_OUTCOME",
              "effect": "...", "error": "..."}
        """
        outcome: AdapterOutcome = AdapterOutcome.from_str((scenario or {}).get("outcome"))
        return self._record_and_return(
            key,
            FakeAdapterResult(
                outcome=outcome,
                effect=(scenario or {}).get("effect", f"effect:{key}"),
                error=(scenario or {}).get("error", ""),
            ),
        )


__all__ = ["FakeAdapterResult", "FakeServiceAdapter"]