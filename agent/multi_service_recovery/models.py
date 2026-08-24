"""Sprint 1.3.16 — recovery & compensation hardening: core immutable models.

Recovery is NOT an authority layer.  It classifies, reconciles, resumes
verification, requests compensation, releases stale safe locks, restores
coordinator state, and raises manual review.  It NEVER grants service control,
mints execution authority, lowers risk, overrides a child DENY/UNKNOWN, or
bypasses approval/budget/lock.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RecoveryDisposition(Enum):
    SAFE_TO_ABORT = "SAFE_TO_ABORT"
    SAFE_TO_CONTINUE_VERIFY = "SAFE_TO_CONTINUE_VERIFY"
    SAFE_TO_RESUME_PREPARE = "SAFE_TO_RESUME_PREPARE"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    TERMINAL = "TERMINAL"
    UNKNOWN_RECOVERY_STATE = "UNKNOWN_RECOVERY_STATE"


class CrashPoint(Enum):
    AFTER_GLOBAL_CLAIM = "AFTER_GLOBAL_CLAIM"
    AFTER_LOCK_1 = "AFTER_LOCK_1"
    AFTER_LOCK_N = "AFTER_LOCK_N"
    AFTER_CHILD_PREPARE = "AFTER_CHILD_PREPARE"
    AFTER_BARRIER_READY = "AFTER_BARRIER_READY"
    BEFORE_SIMULATION = "BEFORE_SIMULATION"
    AFTER_CHILD_A_SIMULATION = "AFTER_CHILD_A_SIMULATION"
    AFTER_CHILD_B_SIMULATION = "AFTER_CHILD_B_SIMULATION"
    BEFORE_VERIFY = "BEFORE_VERIFY"
    DURING_VERIFY = "DURING_VERIFY"
    AFTER_VERIFY_BEFORE_COMMIT = "AFTER_VERIFY_BEFORE_COMMIT"
    AFTER_COMPENSATION_REQUIRED = "AFTER_COMPENSATION_REQUIRED"
    DURING_COMPENSATION = "DURING_COMPENSATION"
    AFTER_COMPENSATION = "AFTER_COMPENSATION"
    AFTER_SIMULATED_COMMIT = "AFTER_SIMULATED_COMMIT"


class PartialState(Enum):
    NOT_STARTED = "NOT_STARTED"
    PREPARED = "PREPARED"
    SIMULATED_EXECUTED = "SIMULATED_EXECUTED"
    VERIFY_PENDING = "VERIFY_PENDING"
    VERIFIED = "VERIFIED"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    FAILED_SAFE = "FAILED_SAFE"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    TERMINAL = "TERMINAL"


class RecoveryEventType(Enum):
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_CLAIMED = "RECOVERY_CLAIMED"
    RECOVERY_STATE_CLASSIFIED = "RECOVERY_STATE_CLASSIFIED"
    VERIFY_RESUME_STARTED = "VERIFY_RESUME_STARTED"
    VERIFY_RESUME_COMPLETED = "VERIFY_RESUME_COMPLETED"
    COMPENSATION_PLANNED = "COMPENSATION_PLANNED"
    COMPENSATION_STARTED = "COMPENSATION_STARTED"
    COMPENSATION_CHILD_COMPLETED = "COMPENSATION_CHILD_COMPLETED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    RECOVERY_COMPLETED = "RECOVERY_COMPLETED"


@dataclass(frozen=True)
class RecoveryEvidence:
    """Durable recovery evidence snapshot.  Immutable, versioned, no caller-
    controlled mutable authority field."""
    global_transaction_id: str
    semantic_key: str
    baseline_sha: str
    plan_hash: str
    graph_digest: str
    service_set_digest: str
    child_states: dict[str, str] = field(default_factory=dict)
    lock_state_digest: str = ""
    budget_state_digest: str = ""
    approval_state_digest: str = ""
    idempotency_state: str = "CLAIMED"
    event_journal_digest: str = ""
    last_known_phase: str = ""
    crash_point: str = ""
    unknown_outcome_flags: tuple[str, ...] = ()
    compensation_required: bool = False
    recovery_generation: int = 0
    created_at_monotonic: float = 0.0
    evidence_version: int = 1

    def frozen(self) -> "RecoveryEvidence":
        return self  # frozen dataclass is already immutable


@dataclass(frozen=True)
class RecoveryClaim:
    """Durable claim-first recovery lease.  Foreign renewal/spoofed/live-owner
    takeover are DENIED at the store layer."""
    transaction_id: str
    recovery_generation: int
    pid: int
    process_start_identity: str
    runtime_identity: str
    host_identity: str
    nonce: str
    lease_created_monotonic: float
    lease_expiry_monotonic: float


@dataclass(frozen=True)
class ManualReviewPayload:
    """Deterministic, read-only, no-secret manual review payload.  Advisory
    commands are text only — never executable authority."""
    transaction_id: str
    service_set: tuple[str, ...]
    last_known_phase: str
    crash_point: str
    child_states: dict[str, str]
    unknown_outcomes: tuple[str, ...]
    lock_state_digest: str
    budget_state_digest: str
    approval_state_digest: str
    compensation_status: str
    evidence_conflicts: tuple[str, ...]
    recommended_operator_action: str
    synthetic_blocking_findings: int = 0

    def advisory_command_text(self) -> str:
        return "Operator review required. No automatic action will be taken."


@dataclass(frozen=True)
class RecoveryPlan:
    """Immutable recovery plan produced by the recovery coordinator.  Carries a
    disposition and the derived would-do flags; never an execution authority."""
    transaction_id: str
    recovery_generation: int
    global_tx_id: str
    semantic_key: str
    disposition: RecoveryDisposition
    crash_point: str
    violation: str = ""
    would_verify: bool = False
    would_compensate: bool = False
    manual_review: bool = False
    conflicts: tuple[str, ...] = ()
    refresh_after_monotonic: float = 0.0

    def expires_after(self, now_monotonic: float) -> bool:
        return self.refresh_after_monotonic > 0 and now_monotonic > self.refresh_after_monotonic


@dataclass(frozen=True)
class CompensationPlan:
    """Immutable compensated plan bound to the executed/verified/failed/unknown
    child set, topological order, baseline and recovery generation."""
    global_tx_id: str
    transaction_id: str
    service_set: tuple[str, ...]
    executed_set: frozenset[str]
    verified_set: frozenset[str]
    failed_child: str
    unknown_children: frozenset[str]
    baseline_sha: str
    plan_hash: str
    recovery_generation: int
    steps: tuple["CompensationStep", ...] = ()

    @property
    def rollback_supported(self) -> bool:
        return all(not s.unsupported for s in self.steps)

    @property
    def order(self) -> tuple[str, ...]:
        return tuple(s.service_id for s in self.steps)


@dataclass(frozen=True)
class CompensationStep:
    service_id: str
    operation: str
    order: int
    preconditions: tuple[str, ...] = ()
    evidence: str = ""
    unsupported: bool = False


@dataclass(frozen=True)
class CompensationKey:
    """Semantic idempotency key for a compensation action (exactly-once)."""
    global_tx_id: str
    child_tx_id: str
    operation: str
    compensation_generation: int
    target_identity: str
    prior_effect_receipt: str

    def value(self) -> str:
        import hashlib
        raw = "|".join([
            self.global_tx_id, self.child_tx_id, self.operation,
            str(self.compensation_generation), self.target_identity,
            self.prior_effect_receipt,
        ])
        return hashlib.sha256(raw.encode()).hexdigest()


__all__ = [
    "RecoveryDisposition", "CrashPoint", "PartialState", "RecoveryEventType",
    "RecoveryEvidence", "RecoveryClaim", "ManualReviewPayload", "RecoveryPlan",
    "CompensationPlan", "CompensationStep", "CompensationKey",
]