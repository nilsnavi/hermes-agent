"""Sprint 1.3.16 — Multi-Service Recovery & Compensation Hardening.

RECOVERY DOES NOT GRANT AUTHORITY.
MULTI-SERVICE EXECUTION: DISABLED.
COMPENSATION EXECUTION: SIMULATED ONLY (no production compensation adapter).

Recovery classifies, reconciles, resumes verification, requests simulated
compensation, releases stale safe locks and raises manual review — it never
mints execution authority, never overrides a child DENY/UNKNOWN, and never
bypasses approval/budget/lock.
"""
from __future__ import annotations

from .models import (CompensationKey, CompensationPlan, CompensationStep,
                     CrashPoint, ManualReviewPayload, PartialState,
                     RecoveryClaim, RecoveryDisposition, RecoveryEvidence,
                     RecoveryEventType, RecoveryPlan)
from .store import RecoveryStore, RECOVERY_EVENTS
from .provenance import Provenance
from .classify import classify_disposition, derive_crash_point, event_order_valid
from .coordinator import MultiServiceRecoveryCoordinator
from .lock_recovery import LockRecoveryState, classify_lock_owner
from .budget_recovery import BudgetState, classify_budget_state
from .approval_recovery import ApprovalRecoveryState, classify_approval
from .compensation import build_compensation_plan, compensation_eligible
from .manual_review import build_manual_review

__all__ = [
    "MultiServiceRecoveryCoordinator", "RecoveryEvidence", "RecoveryClaim",
    "RecoveryDisposition", "CrashPoint", "PartialState", "RecoveryPlan",
    "RecoveryEventType", "ManualReviewPayload", "CompensationPlan",
    "CompensationStep", "CompensationKey", "RecoveryStore", "RECOVERY_EVENTS",
    "Provenance", "classify_disposition", "derive_crash_point",
    "event_order_valid", "classify_lock_owner", "LockRecoveryState",
    "classify_budget_state", "BudgetState", "classify_approval",
    "ApprovalRecoveryState", "build_compensation_plan", "compensation_eligible",
    "build_manual_review",
]