"""Recovery engine (Sprint 1.0.4) — orchestrator.

Entry point for post-restart recovery:

    engine = RecoveryEngine(store, run_engine=run_engine, clock=...)
    report = engine.recover(engine_factory=...)   # scan + safe resume
    # or, controlled single-run:
    result = engine.resume("run-1", engine=engine_instance)

Pipeline: scan incomplete runs → classify → SAFE_TO_RESUME (resume via a
fresh ExecutionEngine) / WAIT_FOR_APPROVAL (keep waiting, no duplicate
request) / REQUIRES_VERIFICATION (verify persisted state first) /
MANUAL_REVIEW (queue, never auto-run) / TERMINAL (ignored).

Nothing is connected to the production gateway; the engine runs against a
SQLiteExecutionStore of the caller's choosing (tests use temp DBs).
"""

from datetime import datetime
from typing import Callable, Optional

from agent.execution.executor import ExecutionEngine
from agent.runtime.events import RuntimeEvent
from agent.runtime.run_engine import RunEngine

from .classifier import RecoveryClassifier
from .events import RECOVERY_VERIFIED, RECOVERY_VERIFYING
from .manual_review import ManualReviewQueue
from .models import RecoveryReport, RunRecoveryResult
from .resume import ResumeCoordinator
from .scanner import RecoveryScanner
from .verification import VerificationRecovery


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class RecoveryEngine:
    """Scan + classify + safely resume incomplete runs after a restart."""

    def __init__(
        self,
        store,
        run_engine: Optional[RunEngine] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._store = store
        self._run_engine = run_engine
        self._clock = clock or _utcnow
        self._classifier = RecoveryClassifier(store)
        self._scanner = RecoveryScanner(store, clock=clock)
        self._verifier = VerificationRecovery(store, clock=clock)
        self._queue = ManualReviewQueue(store, clock=clock)
        self._coordinator = ResumeCoordinator(
            store, run_engine=run_engine, verifier=self._verifier, clock=clock
        )

    @property
    def manual_review(self) -> ManualReviewQueue:
        return self._queue

    # ── API ──────────────────────────────────────────────────────────

    def scan(self) -> RecoveryReport:
        """Classify every incomplete run and bucket the results.

        Writes the scan audit trail (RECOVERY_SCANNED / RECOVERY_CLASSIFIED /
        RECOVERY_WAITING / RECOVERY_MANUAL_REVIEW / RECOVERY_VERIFYING /
        RECOVERY_VERIFIED) to the journal. Executes NOTHING.
        """
        report = RecoveryReport()
        for result in self._scanner.scan(audit=True):
            report.scanned.append(result)
            if result.action == "wait":
                report.waiting.append(result)
            elif result.action == "manual_review":
                report.manual_review.append(result)
                self._queue.add(result.run_id, result.reason, result.disposition)
            elif result.action == "verify":
                report.verification.append(result)
                self._verify_run(result)
            elif result.action == "ignore":
                report.skipped.append(result)
        return report

    def resume(
        self,
        run_id: str,
        engine: Optional[ExecutionEngine] = None,
    ) -> RunRecoveryResult:
        """Controlled resume of ONE run (see ResumeCoordinator.resume)."""
        return self._coordinator.resume(run_id, engine=engine)

    def approve(
        self,
        run_id: str,
        approval_id: str,
        engine: Optional[ExecutionEngine] = None,
    ) -> RunRecoveryResult:
        """Decide a persisted approval and resume the run (post-restart)."""
        return self._coordinator.approve(run_id, approval_id, engine=engine)

    def recover(
        self,
        engine_factory: Optional[Callable[[], ExecutionEngine]] = None,
    ) -> RecoveryReport:
        """Scan, then safely resume every SAFE_TO_RESUME run.

        *engine_factory* builds a fresh ExecutionEngine bound to the same
        store (``engine_factory()`` per resumed run). When omitted, runs
        are classified and reported only — nothing executes.
        """
        report = self.scan()
        for result in list(report.scanned):
            if result.action != "resume":
                continue
            engine = engine_factory() if engine_factory is not None else None
            outcome = self.resume(result.run_id, engine=engine)
            report.resumed.append(outcome)
        return report

    # ── internals ────────────────────────────────────────────────────

    def _verify_run(self, result: RunRecoveryResult) -> None:
        """Run persisted-state verification for a REQUIRES_VERIFICATION run."""
        try:
            run = self._store.get_run(result.run_id)
        except Exception:
            return
        self._store.append_event(RuntimeEvent(
            event_type=RECOVERY_VERIFYING, run_id=run.id,
            timestamp=self._clock(), payload={"disposition": result.disposition},
        ))
        verdict = self._verifier.verify(run)
        if verdict.ok:
            result.reason = "verification passed"
            self._store.append_event(RuntimeEvent(
                event_type=RECOVERY_VERIFIED, run_id=run.id,
                timestamp=self._clock(), payload={},
            ))
        else:
            result.reason = "verification failed: " + "; ".join(verdict.reasons)
            self._queue.add(run.id, result.reason, result.disposition)
