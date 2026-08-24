"""Sprint 1.3.16 — trusted clock model.

* wall clock  -> audit only
* monotonic   -> TTL / lease
* boot/process identity -> ownership proof
* Clock rollback must NOT extend authority: monotonic derives from
  time.monotonic() which never goes backwards for leases.
"""
from __future__ import annotations

import itertools
import time

_NONCE = itertools.count(1)


class TrustedClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def wall(self) -> float:
        return time.time()

    def nonce(self) -> str:
        return f"{self.monotonic():.9f}-{next(_NONCE)}"

    def lease_expiry(self, hold_s: float) -> float:
        return self.monotonic() + hold_s


class FixedClock(TrustedClock):
    """Deterministic clock for tests."""

    def __init__(self, t0: float = 1000.0) -> None:
        self._t = t0
        self._boot = "boot-fixed"

    def monotonic(self) -> float:
        return self._t

    def advance(self, delta: float) -> None:
        assert delta >= 0, "clock only moves forward (rollback cannot extend authority)"
        self._t += delta


__all__ = ["TrustedClock", "FixedClock"]