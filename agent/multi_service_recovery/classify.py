"""Sprint 1.3.16 — deterministic recovery classifier.

Derives a CrashPoint from the durable event journal, validates the event order
(impossible sequences -> RECOVERY_STATE_CORRUPT -> manual review), and maps to a
single fail-closed RecoveryDisposition.  NEVER maps UNKNOWN to safe execution.
"""
from __future__ import annotations

from .models import CrashPoint, RecoveryDisposition, RecoveryEvidence

# Events that indicate forward mutation/simulation progress.
_EFFECT = {"SIMULATION_STARTED", "CHILD_SIMULATED"}
_VERIFY_DONE = {"VERIFY_COMPLETED"}
_COMMIT = {"GLOBAL_SIMULATED_COMMIT", "COMPENSATION_FAILED", "GLOBAL_FAILED"}
_COMPENSATION = {"COMPENSATION_REQUIRED", "CHILD_FAILED"}
_PREPARED = {"CHILD_PREPARED"}
_BARRIER = {"BARRIER_READY"}
_LOCKS = {"LOCK_ACQUIRED"}


def event_order_valid(types: list[str]) -> bool:
    """False => RECOVERY_STATE_CORRUPT.  Impossible sequences are rejected."""
    if not types:
        return True
    # COMMIT without verify evidence
    if any(t in _COMMIT for t in types) and not any(t in _VERIFY_DONE for t in types):
        if "MANUAL_REVIEW_REQUIRED" not in types and "COMPENSATION_REQUIRED" not in types:
            return False
    # compensation before any effect
    if any(t in _COMPENSATION for t in types) and not any(t in _EFFECT for t in types):
        return False
    # barrier without prepared children
    if any(t in _BARRIER for t in types) and not any(t in _PREPARED for t in types):
        return False
    # verify-done without execution evidence
    if any(t in _VERIFY_DONE for t in types) and not any(t in _EFFECT for t in types):
        return False
    # a mutation event after terminal commit
    commit_idx = -1
    for i, t in enumerate(types):
        if t in _COMMIT:
            commit_idx = i
    if commit_idx >= 0:
        for t in types[commit_idx + 1:]:
            if t in _EFFECT or t == "BARRIER_READY":
                return False
    return True


def derive_crash_point(types: list[str]) -> CrashPoint:
    s = set(types)
    if "GLOBAL_SIMULATED_COMMIT" in s or "COMPENSATION_FAILED" in s or "GLOBAL_FAILED" in s:
        return CrashPoint.AFTER_SIMULATED_COMMIT
    if "COMPENSATION_CHILD_COMPLETED" in s:
        return CrashPoint.DURING_COMPENSATION
    if "COMPENSATION_REQUIRED" in s or "CHILD_FAILED" in s:
        return CrashPoint.AFTER_COMPENSATION_REQUIRED
    if "VERIFY_COMPLETED" in s:
        return CrashPoint.AFTER_VERIFY_BEFORE_COMMIT
    if "CHILD_SIMULATED" in s:
        n = sum(1 for t in types if t == "CHILD_SIMULATED")
        return CrashPoint.AFTER_CHILD_B_SIMULATION if n >= 2 else CrashPoint.AFTER_CHILD_A_SIMULATION
    if "SIMULATION_STARTED" in s:
        return CrashPoint.BEFORE_VERIFY
    if "BARRIER_READY" in s:
        return CrashPoint.AFTER_BARRIER_READY
    if "CHILD_PREPARED" in s:
        return CrashPoint.AFTER_CHILD_PREPARE
    if "LOCK_ACQUIRED" in s:
        return CrashPoint.AFTER_LOCK_N if s >= {"LOCK_ACQUIRED", "CHILD_PREPARED"} else CrashPoint.AFTER_LOCK_1
    if "GLOBAL_CLAIMED" in s:
        return CrashPoint.AFTER_GLOBAL_CLAIM
    return CrashPoint.AFTER_GLOBAL_CLAIM


def classify_disposition(
    types: list[str],
    child_states: dict[str, str] | None = None,
    evidence: RecoveryEvidence | None = None,
) -> RecoveryDisposition:
    """Single, deterministic, fail-closed disposition from durable evidence."""
    child_states = child_states or {}
    # 1. unknown outcome anywhere => manual review (never safe execution)
    if any(v == "UNKNOWN_OUTCOME" for v in child_states.values()):
        return RecoveryDisposition.MANUAL_REVIEW_REQUIRED
    # 2. corrupt / impossible event order => manual review
    if not event_order_valid(types):
        return RecoveryDisposition.MANUAL_REVIEW_REQUIRED
    # 2b. no durable evidence at all => unknown recovery state (fail closed)
    if not types:
        return RecoveryDisposition.UNKNOWN_RECOVERY_STATE
    s = set(types)
    # 3. durable terminal => TERMINAL (immutable, inspect-only)
    if any(t in ("GLOBAL_SIMULATED_COMMIT", "GLOBAL_FAILED", "RECOVERY_COMPLETED", "COMPENSATION_FAILED") for t in types):
        return RecoveryDisposition.TERMINAL
    # 3b. a FAILED child with execution evidence => compensation required, never SAFE
    if any(v in ("FAILED_SAFE", "COMPENSATION_REQUIRED") for v in child_states.values()) \
       and any(t in _EFFECT for t in types):
        return RecoveryDisposition.COMPENSATION_REQUIRED
    # 4. compensation required
    if any(t in ("COMPENSATION_REQUIRED", "CHILD_FAILED") for t in types):
        return RecoveryDisposition.COMPENSATION_REQUIRED
    # 5. crash-point driven (pre-execution)
    cp = derive_crash_point(types)
    if cp in (CrashPoint.AFTER_GLOBAL_CLAIM, CrashPoint.AFTER_LOCK_1,
              CrashPoint.AFTER_LOCK_N, CrashPoint.AFTER_CHILD_PREPARE,
              CrashPoint.AFTER_BARRIER_READY):
        return RecoveryDisposition.SAFE_TO_RESUME_PREPARE
    if cp in (CrashPoint.BEFORE_SIMULATION, CrashPoint.BEFORE_VERIFY,
              CrashPoint.AFTER_CHILD_A_SIMULATION, CrashPoint.AFTER_CHILD_B_SIMULATION,
              CrashPoint.DURING_VERIFY, CrashPoint.AFTER_VERIFY_BEFORE_COMMIT):
        return RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY
    if cp in (CrashPoint.AFTER_COMPENSATION_REQUIRED, CrashPoint.DURING_COMPENSATION,
              CrashPoint.AFTER_COMPENSATION):
        return RecoveryDisposition.COMPENSATION_REQUIRED
    # 6. no evidence at all => unknown recovery state (fail closed)
    if not types:
        return RecoveryDisposition.UNKNOWN_RECOVERY_STATE
    return RecoveryDisposition.UNKNOWN_RECOVERY_STATE


def global_state_from_children(child_states: dict[str, str]) -> str:
    """Derive global state from child partial-mutation states.

    Never returns PARTIAL_COMMIT_SUCCESS.  Any UNKNOWN -> UNKNOWN_OUTCOME;
    any FAILED (with an executed child) -> COMPENSATION_REQUIRED; all VERIFIED
    (with execution evidence) -> COMMITTED; else FAILED_SAFE.
    """
    vals = set(child_states.values())
    if "UNKNOWN_OUTCOME" in vals:
        return "UNKNOWN_OUTCOME"
    executed_children = {s for s, v in child_states.items()
                         if v in ("SIMULATED_EXECUTED", "VERIFIED", "COMPENSATION_REQUIRED",
                                  "COMPENSATING", "COMPENSATED", "FAILED_SAFE")}
    if executed_children and ("FAILED_SAFE" in vals or "COMPENSATION_REQUIRED" in vals):
        return "COMPENSATION_REQUIRED"
    if executed_children and all(v in ("VERIFIED", "COMPENSATED", "TERMINAL") for v in vals):
        return "COMMITTED"
    if "FAILED_SAFE" in vals:
        return "FAILED_SAFE"
    return "NOT_STARTED"


__all__ = ["event_order_valid", "derive_crash_point", "classify_disposition",
           "global_state_from_children"]