"""Sprint 1.3.16 — approval recovery.

Approval stays single-use.  Recovery NEVER mints a new approval.  States:
  VALID_FOR_RECOVERY_VERIFY / INVALIDATED / CONSUMED / EXPIRED / MISMATCH
Any plan/profile/service-set change invalidates the approval.
"""
from __future__ import annotations

from enum import Enum


class ApprovalRecoveryState(Enum):
    VALID_FOR_RECOVERY_VERIFY = "VALID_FOR_RECOVERY_VERIFY"
    INVALIDATED = "INVALIDATED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    MISMATCH = "MISMATCH"


def classify_approval(*, consumed: bool = False, expired: bool = False,
                      mismatch: bool = False, revoked: bool = False) -> ApprovalRecoveryState:
    """Deterministic approval classification (fail-closed: any flaw -> not valid)."""
    if mismatch or revoked:
        return ApprovalRecoveryState.MISMATCH
    if consumed:
        return ApprovalRecoveryState.CONSUMED
    if expired:
        return ApprovalRecoveryState.EXPIRED
    return ApprovalRecoveryState.VALID_FOR_RECOVERY_VERIFY


def approval_valid(state: ApprovalRecoveryState) -> bool:
    """Recovery may use an approval only for verification resume, never to start
    a new mutation."""
    return state == ApprovalRecoveryState.VALID_FOR_RECOVERY_VERIFY


__all__ = ["ApprovalRecoveryState", "classify_approval", "approval_valid"]