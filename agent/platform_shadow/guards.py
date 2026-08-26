"""Shadow runtime guards: backpressure budget + isolation (Phase 7 §20, §21, §24).

``ShadowBudget`` bounds concurrency, queue depth and per-task/agent time so the
shadow runtime can NEVER saturate or stall production (on overload it raises
``ShadowOverloaded`` so the caller DROPs/SKIPs shadow). ``IsolationGuard`` is the
mechanical "no production callable may enter" check used at the shadow boundary.
"""

from __future__ import annotations

import threading
import time

from .exceptions import ShadowIsolationError, ShadowOverloaded, ShadowTimeout


class ShadowBudget:
    """Bounded resource budget for shadow work (never blocks production indefinitely)."""

    __slots__ = ("_sem", "_timeout_ms", "_lock")

    def __init__(self, *, max_concurrent: int, acquire_timeout_ms: int) -> None:
        if not isinstance(max_concurrent, int) or max_concurrent < 1:
            raise ValueError("max_concurrent must be a positive integer")
        if not isinstance(acquire_timeout_ms, int) or acquire_timeout_ms < 0:
            raise ValueError("acquire_timeout_ms must be >= 0")
        self._sem = threading.BoundedSemaphore(max_concurrent)
        self._timeout_ms = acquire_timeout_ms
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block up to ``acquire_timeout_ms`` for a slot; else raise ShadowOverloaded."""
        deadline = time.monotonic() + self._timeout_ms / 1000.0
        while True:
            if self._sem.acquire(blocking=False):
                return
            if time.monotonic() >= deadline:
                raise ShadowOverloaded(
                    f"shadow budget exhausted (no slot within {self._timeout_ms}ms); SKIP shadow"
                )
            time.sleep(0.001)  # bounded, short poll -- production path unaffected

    def release(self) -> None:
        self._sem.release()

    def try_acquire_nowait(self) -> bool:
        return self._sem.acquire(blocking=False)


class TimeBudget:
    """Monotonic deadline; raises ShadowTimeout when elapsed (record only)."""

    __slots__ = ("_deadline",)

    def __init__(self, timeout_ms: int) -> None:
        if not isinstance(timeout_ms, int) or timeout_ms < 0:
            raise ValueError("timeout_ms must be >= 0")
        self._deadline = time.monotonic() + timeout_ms / 1000.0

    def check(self) -> None:
        if time.monotonic() > self._deadline:
            raise ShadowTimeout("bounded shadow time budget elapsed")


class IsolationGuard:
    """Mechanical proof helpers: production-side callables are DENIED here."""

    # The single shadow-side read surface that MAY be invoked. Nothing else.
    ALLOWED_EXECUTE_SURFACES = ("ReadOnlyProvider", "SealedSandbox.run", "build_read_only_gate")

    @staticmethod
    def is_shadow_side_callable(name: str) -> bool:
        return name in IsolationGuard.ALLOWED_EXECUTE_SURFACES

    @staticmethod
    def reject_production_side(value: object, label: str) -> None:
        """Treat a callable/executor/adapter as a forbidden production side.

        Any value that is callable and is NOT one of the shadow-side read
        surfaces is rejected, so a production executor/override can never be
        smuggled into the shadow runtime.
        """
        if value is None or not callable(value):
            return
        if getattr(value, "__name__", "") in IsolationGuard.ALLOWED_EXECUTE_SURFACES:
            return
        raise ShadowIsolationError(f"forbidden production-side callable under {label!r}")


__all__ = [
    "IsolationGuard",
    "ShadowBudget",
    "TimeBudget",
]