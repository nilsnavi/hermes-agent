"""Retry policy V2 (Sprint 0.7 §7): exponential backoff + jitter.

Base schedule (seconds, configurable):
    first retry: 5 min → 15 min → 30 min → 60 min → 6 h (cap)

Jitter ±10–20% (default 15%).  Deterministic when a seeded RNG is provided
(used by tests / controlled time simulation).  Backoff resets on success.
"""

from __future__ import annotations

import random
from typing import List, Optional

DEFAULT_BASE_SECONDS: List[int] = [300, 900, 1800, 3600, 21600]  # 5m/15m/30m/60m/6h
DEFAULT_JITTER = 0.15  # ±15%


def next_delay(
    attempt: int,
    base: Optional[List[int]] = None,
    jitter_frac: float = DEFAULT_JITTER,
    rng: Optional[random.Random] = None,
) -> float:
    """Delay before retry ``attempt`` (1-based).

    attempt=1 → base[0] (5 min), attempt=2 → 15 min, … capped at base[-1].
    Jitter applied in [1-jitter_frac, 1+jitter_frac].
    """
    steps = list(base if base is not None else DEFAULT_BASE_SECONDS)
    if not steps:
        return 0.0
    cap = steps[-1]
    idx = min(max(attempt, 1) - 1, len(steps) - 1)
    delay = float(min(steps[idx], cap))
    rng_inst = rng if rng is not None else random.Random()
    jitter = 1.0 + rng_inst.uniform(-jitter_frac, jitter_frac)
    return max(0.0, delay * jitter)


def should_retry(error_class: str, non_retryable=None) -> bool:
    """Non-retryable: auth invalid/expired, misconfigured, disabled."""
    from .classifier import is_retryable

    return is_retryable(error_class)


def reset_on_success(attempt: int) -> int:
    return 0