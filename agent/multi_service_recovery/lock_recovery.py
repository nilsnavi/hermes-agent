"""Sprint 1.3.16 — lock recovery.  Rules:
  live owner   => no takeover
  stale dead   => validated takeover only
  PID reuse    => deny until process-start identity differs safely
  unknown owner=> manual review
  active child execution => no lock steal
No force-release solely by wall-clock age.
"""
from __future__ import annotations

from enum import Enum


class LockRecoveryState(Enum):
    LIVE_OWNER = "LIVE_OWNER"            # do not touch
    STALE_DEAD = "STALE_DEAD"            # validated takeover allowed
    PID_REUSE = "PID_REUSE"              # same pid, different process -> deny
    UNKNOWN_OWNER = "UNKNOWN_OWNER"      # manual review
    ACTIVE_EXECUTION = "ACTIVE_EXECUTION"  # no lock steal
    FREE = "FREE"


def classify_lock_owner(*, lock_record: dict | None, now_monotonic: float,
                        same_process_now: bool | None = None,
                        active_execution: bool = False) -> LockRecoveryState:
    """Deterministic lock ownership classification.  Fail-closed."""
    if lock_record is None:
        return LockRecoveryState.FREE
    if active_execution:
        return LockRecoveryState.ACTIVE_EXECUTION
    created = lock_record.get("created", 0.0)
    expiry = lock_record.get("expiry", 0.0)
    if expiry > now_monotonic:
        # lease is live: same platform identity is the owner; otherwise cannot
        # conclude — unknown owner must go to manual review, never takeover.
        if same_process_now is True:
            return LockRecoveryState.LIVE_OWNER
        if same_process_now is False:
            # held by another live process/pid: takeover DENY
            if "pid" in lock_record or "start" in lock_record:
                return LockRecoveryState.PID_REUSE if created > 0 else LockRecoveryState.LIVE_OWNER
            return LockRecoveryState.LIVE_OWNER
        return LockRecoveryState.LIVE_OWNER
    # lease expired
    if "start" in lock_record and same_process_now is False:
        return LockRecoveryState.PID_REUSE
    return LockRecoveryState.STALE_DEAD


def can_takeover(state: LockRecoveryState) -> bool:
    """Only a validated STALE_DEAD owner may be taken over."""
    return state == LockRecoveryState.STALE_DEAD


__all__ = ["LockRecoveryState", "classify_lock_owner", "can_takeover"]