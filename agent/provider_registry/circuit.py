"""Circuit breaker for provider routing (Sprint 0.4 §9)."""

from __future__ import annotations

import time
from typing import Callable, Optional

from .domain import CircuitState


class CircuitBreaker:
    """Per-provider circuit breaker.

    - consecutive retryable failures >= threshold → OPEN
    - OPEN for cooldown seconds → HALF_OPEN (lazy transition on read)
    - HALF_OPEN success → CLOSED
    - HALF_OPEN failure → OPEN (cooldown restarts)

    Permanent (non-retryable) failures do NOT trip the circuit: the
    registry disables routing eligibility directly (see registry.record_failure).
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        open_cooldown_seconds: float = 60.0,
        now_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.failure_threshold = max(1, int(failure_threshold))
        self.open_cooldown_seconds = max(0.0, float(open_cooldown_seconds))
        self._now = now_fn or time.time

    def record_failure(self, definition) -> bool:
        """Check consecutive failures; returns True if circuit just opened.

        The registry owns the counter (consecutiveFailures += 1 per failure);
        this method only tests the threshold and drives state transitions.
        """
        if (
            definition.circuitState == CircuitState.CLOSED
            and definition.consecutiveFailures >= self.failure_threshold
        ):
            definition.circuitState = CircuitState.OPEN
            definition.circuitOpenedAt = self._now()
            return True
        if definition.circuitState == CircuitState.HALF_OPEN:
            # probe failed → back to OPEN
            definition.circuitState = CircuitState.OPEN
            definition.circuitOpenedAt = self._now()
            return True
        return False

    def record_success(self, definition) -> bool:
        """Reset failure count; close circuit if half-open/open; returns True if closed."""
        definition.consecutiveFailures = 0
        if definition.circuitState in (CircuitState.OPEN, CircuitState.HALF_OPEN):
            definition.circuitState = CircuitState.CLOSED
            definition.circuitOpenedAt = None
            return True
        return False

    def maybe_half_open(self, definition) -> bool:
        """Lazily transition OPEN → HALF_OPEN after cooldown. Returns True on transition."""
        if (
            definition.circuitState == CircuitState.OPEN
            and definition.circuitOpenedAt is not None
            and (self._now() - definition.circuitOpenedAt) >= self.open_cooldown_seconds
        ):
            definition.circuitState = CircuitState.HALF_OPEN
            return True
        return False

    def open_now(self, definition) -> bool:
        """Force-open (e.g. permanent-class first failure is not used, but explicit)."""
        if definition.circuitState != CircuitState.OPEN:
            definition.circuitState = CircuitState.OPEN
            definition.circuitOpenedAt = self._now()
            return True
        return False

    def is_open(self, definition) -> bool:
        return definition.circuitState == CircuitState.OPEN

    def effective_state(self, definition) -> CircuitState:
        self.maybe_half_open(definition)
        return definition.circuitState
