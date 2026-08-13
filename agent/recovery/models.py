"""Recovery result models (Sprint 1.0.4).

Plain dataclasses — no gateway dependency, JSON-safe via ``to_dict`` so a
report can be persisted or delivered.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RunRecoveryResult:
    """Outcome of scanning / recovering ONE run."""

    run_id: str
    run_status: str
    disposition: str
    action: str
    reason: str = ""
    event_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_status": self.run_status,
            "disposition": self.disposition,
            "action": self.action,
            "reason": self.reason,
            "event_count": self.event_count,
        }


@dataclass
class RecoveryReport:
    """Aggregate of a recovery scan + resume pass."""

    scanned: List[RunRecoveryResult] = field(default_factory=list)
    resumed: List[RunRecoveryResult] = field(default_factory=list)
    waiting: List[RunRecoveryResult] = field(default_factory=list)
    verification: List[RunRecoveryResult] = field(default_factory=list)
    manual_review: List[RunRecoveryResult] = field(default_factory=list)
    skipped: List[RunRecoveryResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scanned": [r.to_dict() for r in self.scanned],
            "resumed": [r.to_dict() for r in self.resumed],
            "waiting": [r.to_dict() for r in self.waiting],
            "verification": [r.to_dict() for r in self.verification],
            "manual_review": [r.to_dict() for r in self.manual_review],
            "skipped": [r.to_dict() for r in self.skipped],
        }

    def counts(self) -> Dict[str, int]:
        return {
            "scanned": len(self.scanned),
            "resumed": len(self.resumed),
            "waiting": len(self.waiting),
            "verification": len(self.verification),
            "manual_review": len(self.manual_review),
            "skipped": len(self.skipped),
        }


@dataclass
class VerificationResult:
    """Persisted-state verification outcome for one run.

    ``ok=True`` means the journal + persisted step results PROVE every
    started tool completed — no tool was re-run, nothing was guessed.
    """

    run_id: str
    ok: bool
    missing_steps: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "ok": self.ok,
            "missing_steps": list(self.missing_steps),
            "reasons": list(self.reasons),
        }


@dataclass
class ManualReviewItem:
    """One run queued for human review (never auto-resumed)."""

    run_id: str
    reason: str
    disposition: str
    resolved: bool = False
    decision: Optional[str] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "reason": self.reason,
            "disposition": self.disposition,
            "resolved": self.resolved,
            "decision": self.decision,
            "note": self.note,
        }
