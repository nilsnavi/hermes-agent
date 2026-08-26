"""Durable shadow-run claim store (Phase 7 §10, closes Phase 6 debt).

Semantics required for a durable (post-restart) idempotency:
  semantic key   - deterministic idempotency key derived from the bound identity
  claim-first    - the FIRST claimer of a key wins
  single winner  - concurrent/repeat claims lose
  terminal replay- a terminal outcome is replayed (later identical tasks skip)
  bounded wait   - claiming never blocks unboundedly
  fail-closed    - an unknown backend state -> UNKNOWN (runtime must NOT run a
                    duplicate and must NOT treat shadow as executed)

A PostgreSQL backend is supported as a Protocol port; this module ships a
deterministic in-memory (durable-ready) test backend and is stdlib-only (no DB
import, so it can never touch production storage).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ClaimState(Enum):
    WIN = "win"
    LOST_DUPLICATE = "lost_duplicate"
    UNKNOWN = "unknown"  # fail-closed: backend couldn't resolve


@dataclass(frozen=True, slots=True)
class ShadowClaim:
    state: ClaimState
    key: str
    winner: str = ""


class ShadowClaimStore(Protocol):
    """Port for a durable claim backend (PostgreSQL adapter satisfies this)."""

    def claim(self, key: str, claimer: str) -> ShadowClaim: ...

    def terminal(self, key: str) -> None: ...

    def is_terminal(self, key: str) -> bool: ...


class InMemoryClaimStore:
    """Deterministic, durable-ready test backend (single-winner, terminal replay)."""

    __slots__ = ("_claims", "_terminal", "_lock", "_healthy")

    def __init__(self, *, healthy: bool = True) -> None:
        self._claims: dict[str, str] = {}
        self._terminal: set[str] = set()
        self._lock = threading.Lock()
        self._healthy = healthy

    def claim(self, key: str, claimer: str) -> ShadowClaim:
        if not isinstance(key, str) or not key:
            raise ValueError("claim key must be a non-empty string")
        if not self._healthy:
            # Fail-closed: unknown state -> runtime must NOT run a duplicate.
            return ShadowClaim(ClaimState.UNKNOWN, key)
        with self._lock:
            if key in self._terminal:
                return ShadowClaim(ClaimState.LOST_DUPLICATE, key, winner="")
            if key in self._claims:
                return ShadowClaim(ClaimState.LOST_DUPLICATE, key, winner=self._claims[key])
            self._claims[key] = claimer
            return ShadowClaim(ClaimState.WIN, key, winner=claimer)

    def terminal(self, key: str) -> None:
        with self._lock:
            self._terminal.add(key)
            self._claims.pop(key, None)

    def is_terminal(self, key: str) -> bool:
        with self._lock:
            return key in self._terminal

    @property
    def healthy(self) -> bool:
        return self._healthy


__all__ = [
    "ClaimState",
    "InMemoryClaimStore",
    "ShadowClaim",
    "ShadowClaimStore",
]