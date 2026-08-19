"""Sprint 1.3.12 — stop contract (fake runtime only, no real stop calls).

Models expected stop semantics: active/running -> deactivating -> inactive/dead.
evaluate_stop is pure analysis; it never issues a real stop.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from collections.abc import Sequence

# Re-export StopState from models so callers can import stop states from one place.
from .models import StopState  # noqa: F401  (re-export)


class StopVerdict(Enum):
    STOPPED = "STOPPED"
    UNKNOWN = "UNKNOWN"
    STOP_FAILED = "STOP_FAILED"
    STOP_TIMEOUT = "STOP_TIMEOUT"
    FAIL = "FAIL"


@dataclass(frozen=True)
class StopResult:
    verdict: StopVerdict
    state: StopState
    reason: str = ""


def evaluate_stop(
    current: str,
    expected_path: Sequence[str],
    reached: str,
    timeout_ok: bool = True,
    old_pid_gone: bool = True,
) -> StopResult:
    """Evaluate a modelled stop outcome. Pure; no side effects."""
    # old PID must be gone for a clean stop.
    if not old_pid_gone:
        return StopResult(StopVerdict.FAIL, StopState.STOP_UNKNOWN,
                          "old pid still present")

    # Timeout / not-yet-reached -> unknown outcome (must NOT blindly start).
    if not timeout_ok:
        return StopResult(StopVerdict.UNKNOWN, StopState.STOP_UNKNOWN,
                          "stop timeout / deactivating")

    # Reached the expected terminal member of the path.
    terminal = expected_path[-1] if expected_path else "inactive"
    if reached == terminal:
        return StopResult(StopVerdict.STOPPED, StopState.STOPPED)

    if reached in (current, "deactivating"):
        return StopResult(StopVerdict.UNKNOWN, StopState.STOP_UNKNOWN,
                          f"reached={reached} not terminal")

    return StopResult(StopVerdict.FAIL, StopState.STOP_UNKNOWN,
                      f"unexpected reached={reached}")


__all__ = ["StopResult", "StopState", "StopVerdict", "evaluate_stop"]