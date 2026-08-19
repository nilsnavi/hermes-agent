"""Sprint 1.3.12 — start contract (fake runtime only, no real start calls).

Models unit expected-active + new PID + expected executable/user + warmup +
health. evaluate_start is pure analysis.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Re-export StartState for convenience.
from .models import StartState  # noqa: F401  (re-export)


class StartVerdict(Enum):
    STARTED_VERIFIED = "STARTED_VERIFIED"
    START_FAILED = "START_FAILED"
    START_UNKNOWN = "START_UNKNOWN"


@dataclass(frozen=True)
class StartResult:
    verdict: StartVerdict
    state: StartState
    reason: str = ""


def evaluate_start(
    new_pid,
    new_pid_required: bool = True,
    expected_executable: str = "",
    actual_executable: str = "",
    expected_user: str = "",
    actual_user: str = "",
    unit: str = "",
    expected_unit: str = "active",
    warmup_ok: bool = True,
    health_ok: bool = True,
    unknown: bool = False,
) -> StartResult:
    """Evaluate a modelled start outcome. Pure; no side effects."""
    if unknown:
        return StartResult(StartVerdict.START_UNKNOWN, StartState.START_UNKNOWN,
                           "start outcome unknown")

    if new_pid_required and not new_pid:
        return StartResult(StartVerdict.START_FAILED, StartState.START_REQUESTED,
                           "no new pid")

    if expected_executable and actual_executable != expected_executable:
        return StartResult(StartVerdict.START_FAILED, StartState.START_REQUESTED,
                           "executable mismatch")

    if expected_user and actual_user != expected_user:
        return StartResult(StartVerdict.START_FAILED, StartState.START_REQUESTED,
                           "user mismatch")

    if unit != expected_unit:
        return StartResult(StartVerdict.START_UNKNOWN, StartState.START_UNKNOWN,
                           f"unit={unit} expected={expected_unit}")

    if not warmup_ok:
        return StartResult(StartVerdict.START_UNKNOWN, StartState.START_UNKNOWN,
                           "warmup not ok")

    if not health_ok:
        return StartResult(StartVerdict.START_FAILED, StartState.START_REQUESTED,
                           "health fail")

    return StartResult(StartVerdict.STARTED_VERIFIED, StartState.STARTED_VERIFIED)


__all__ = ["StartResult", "StartState", "StartVerdict", "evaluate_start"]