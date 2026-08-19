"""Sprint 1.3.12 — PID transition model.

Restart success requires new_pid != old_pid (unless a contract proves otherwise).
PID reuse is detected via PID + process-start identity, not PID alone.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import ProcessIdentity


class TransitionVerdict(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TransitionResult:
    verdict: TransitionVerdict
    pid_reuse_detected: bool = False
    reason: str = ""


def validate_transition(old: ProcessIdentity, new: ProcessIdentity | None) -> TransitionResult:
    """Validate that new is a genuine successor process to old."""
    if new is None:
        return TransitionResult(TransitionVerdict.UNKNOWN, reason="no new process")

    # Same PID + same start identity -> the old PID survives.
    if new.pid == old.pid and new.start_identity == old.start_identity:
        return TransitionResult(
            TransitionVerdict.FAIL, pid_reuse_detected=False, reason="old pid survives"
        )

    # Same PID but different start identity -> PID was reused by a new process.
    if new.pid == old.pid and new.start_identity != old.start_identity:
        return TransitionResult(
            TransitionVerdict.FAIL, pid_reuse_detected=True, reason="pid reuse"
        )

    # A new process must carry a fresh process-start identity.
    if not new.start_identity:
        return TransitionResult(TransitionVerdict.FAIL, reason="empty start identity")

    # Executable / user / cgroup must match the expected service identity.
    if new.executable != old.executable:
        return TransitionResult(TransitionVerdict.FAIL, reason="executable changed")
    if new.user != old.user:
        return TransitionResult(TransitionVerdict.FAIL, reason="user changed")
    if old.cgroup and new.cgroup and new.cgroup != old.cgroup:
        return TransitionResult(TransitionVerdict.FAIL, reason="cgroup changed")

    return TransitionResult(TransitionVerdict.PASS)


def verify_start(old: ProcessIdentity, new: ProcessIdentity | None) -> str:
    """Post-start verification string: STARTED_VERIFIED / START_FAILED / START_UNKNOWN."""
    if new is None:
        return "START_UNKNOWN"
    r = validate_transition(old, new)
    if r.verdict == TransitionVerdict.PASS:
        return "STARTED_VERIFIED"
    if r.verdict == TransitionVerdict.UNKNOWN:
        return "START_UNKNOWN"
    return "START_FAILED"


__all__ = ["TransitionResult", "TransitionVerdict", "validate_transition", "verify_start"]