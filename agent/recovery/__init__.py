"""Hermes Agent 2.0 — Recovery Engine (Sprint 1.0.4).

Post-restart recovery: scan incomplete runs from the durable store,
classify each one, and safely resume ONLY ``SAFE_TO_RESUME`` states.
WAIT_FOR_APPROVAL runs keep waiting on their existing approval; ambiguous
tool outcomes go to manual review (never auto-retried); terminal runs are
ignored. Full recovery audit trail in the durable event journal.

    RunEngine ──┐
    ExecutionEngine ──┼──► SQLiteExecutionStore ──► state.db
                    │            ▲
    RecoveryEngine ─┘            │
      ├── RecoveryScanner        │  reads runs/plans/steps/approvals/events
      ├── RecoveryClassifier     │
      ├── ResumeCoordinator ─────┘  drives a FRESH ExecutionEngine (resume_plan)
      ├── VerificationRecovery      (persisted-state verification, no tools)
      └── ManualReviewQueue         (human-review queue, audit-trailed)

Production gateway is NOT integrated (activation is a later stage).
Standalone package — tests use temporary SQLite databases only.
"""

from .classifier import RecoveryClassifier
from .engine import RecoveryEngine
from .events import RECOVERY_EVENT_TYPES
from .exceptions import NotResumable, RecoveryConflict, RecoveryErrorBase
from .manual_review import ManualReviewQueue
from .models import (
    ManualReviewItem,
    RecoveryReport,
    RunRecoveryResult,
    VerificationResult,
)
from .resume import ResumeCoordinator
from .scanner import RecoveryScanner
from .verification import VerificationRecovery

__all__ = [
    "RecoveryEngine",
    "RecoveryScanner",
    "RecoveryClassifier",
    "ResumeCoordinator",
    "VerificationRecovery",
    "ManualReviewQueue",
    "RecoveryReport",
    "RunRecoveryResult",
    "VerificationResult",
    "ManualReviewItem",
    "RECOVERY_EVENT_TYPES",
    "RecoveryErrorBase",
    "NotResumable",
    "RecoveryConflict",
]
