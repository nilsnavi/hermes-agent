"""Sprint 1.3.16 — MultiServiceRecoveryCoordinator.

Loads durable global transaction, child states, event journal, lock,
idempotency, budget and approval state; claims the recovery lease
(exactly-one owner); derives the crash point; reconciles evidence; computes a
single fail-closed disposition; and produces an IMMUTABLE RecoveryPlan.

The recovery coordinator NEVER executes an adapter.  It classifies, resumes
verification, requests compensation (simulated), releases stale safe locks and
raises manual review — it never grants authority.
"""
from __future__ import annotations

from .classify import classify_disposition
from .classify import derive_crash_point, global_state_from_children
from .clock import TrustedClock
from .manual_review import build_manual_review
from .models import (ManualReviewPayload, RecoveryDisposition, RecoveryEvidence,
                     RecoveryPlan)
from .provenance import Provenance
from .reconcile import reconcile
from .store import RecoveryStore
from .lock_recovery import LockRecoveryState, classify_lock_owner

_MAX_AUTO_RECOVERY_GENERATIONS = 8


class MultiServiceRecoveryCoordinator:
    def __init__(self, store: RecoveryStore, *, provenance: Provenance,
                 clock: TrustedClock, transaction_id: str,
                 semantic_key: str, baseline_sha: str, plan_hash: str,
                 graph_digest: str, service_set: tuple[str, ...],
                 recovery_generation: int = 1) -> None:
        self.store = store
        self.prov = provenance
        self.clock = clock
        self.tx_id = transaction_id
        self.semantic_key = semantic_key
        self.baseline_sha = baseline_sha
        self.plan_hash = plan_hash
        self.graph_digest = graph_digest
        self.service_set = service_set
        self.generation = recovery_generation
        assert recovery_generation <= _MAX_AUTO_RECOVERY_GENERATIONS, \
            "exceeded maximum automatic recovery generations"

    def _claim(self) -> bool:
        """Claim-first: exactly one recovery owner.  Live owner never taken over."""
        clock = self.clock
        res = self.store.claims.claim(
            self.tx_id, self.generation,
            pid=self.prov.pid,
            process_start_identity=self.prov.process_start_identity,
            runtime_identity=self.prov.runtime_identity,
            nonce=clock.nonce(),
            lease_created=clock.monotonic(),
            lease_expiry=clock.lease_expiry(hold_s=60.0),
            host_identity=self.prov.host_identity,
        )
        if res == "CLAIMED":
            self.store.journal.append("RECOVERY_CLAIMED", {"tx": self.tx_id, "gen": self.generation})
        return res == "CLAIMED"

    def recover(self, *, journal_types: list[str],
                child_states: dict[str, str] | None = None,
                idempotency_state: str = "CLAIMED",
                lock_record: dict | None = None,
                budget_state: dict[str, str] | None = None,
                approval_consumed: bool = False,
                approval_expired: bool = False,
                approval_mismatch: bool = False,
                child_receipts: dict[str, str] | None = None,
                current_baseline_sha: str | None = None,
                drift_graph: bool = False,
                service_identity_drift: bool = False,
                now_monotonic: float | None = None) -> RecoveryPlan:
        """Produce an immutable recovery plan.  adapter_calls = 0 always."""
        self.store.journal.append("RECOVERY_STARTED", {"tx": self.tx_id, "gen": self.generation})
        claimed = self._claim()
        if not claimed:
            # another recovery worker owns it -> fall back to a read-only plan
            return RecoveryPlan(
                transaction_id=self.tx_id, recovery_generation=self.generation,
                global_tx_id=self.tx_id, semantic_key=self.semantic_key,
                disposition=RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
                crash_point="", violation="RECOVERY_OWNED_BY_OTHER",
                manual_review=True,
                conflicts=("recovery-claim-unavailable",),
            )
        child_states = child_states or {}
        nm = now_monotonic if now_monotonic is not None else self.clock.monotonic()

        evidence = RecoveryEvidence(
            global_transaction_id=self.tx_id, semantic_key=self.semantic_key,
            baseline_sha=self.baseline_sha, plan_hash=self.plan_hash,
            graph_digest=self.graph_digest,
            service_set_digest=",".join(sorted(self.service_set)),
            child_states=child_states, idempotency_state=idempotency_state,
            unknown_outcome_flags=tuple(s for s, v in child_states.items() if v == "UNKNOWN_OUTCOME"),
            recovery_generation=self.generation,
            created_at_monotonic=nm,
        )

        # --- authority-relevant drift checks (fail closed) ---
        if current_baseline_sha is not None and current_baseline_sha != self.baseline_sha:
            return self._plan(evidence, journal_types,
                              RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
                              "BASELINE_DRIFT", would_verify=False,
                              would_compensate=False, manual_review=True,
                              conflicts=("baseline-drift",))
        if drift_graph or service_identity_drift:
            return self._plan(evidence, journal_types,
                              RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
                              "DRIFT", would_verify=False, would_compensate=False,
                              manual_review=True,
                              conflicts=(("graph-drift" if drift_graph else ""),
                                         ("identity-drift" if service_identity_drift else "")))

        # --- lock recovery (no steal / no wall-clock force release) ---
        lock_state = classify_lock_owner(
            lock_record=lock_record, now_monotonic=nm,
            same_process_now=Provenance.same_process(
                lock_record["pid"], lock_record["start"]
            ) if lock_record else None,
        )
        if lock_state in (LockRecoveryState.UNKNOWN_OWNER,
                          LockRecoveryState.ACTIVE_EXECUTION,
                          LockRecoveryState.PID_REUSE):
            return self._plan(evidence, journal_types,
                              RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
                              f"LOCK_{lock_state.value}", manual_review=True,
                              conflicts=(f"lock-{lock_state.value.lower()}",))

        # --- evidence reconciliation ---
        conflicts = reconcile(evidence, journal_types, lock_record=lock_record,
                              budget=budget_state, child_receipts=child_receipts)
        if conflicts:
            return self._plan(evidence, journal_types,
                              RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
                              "RECONCILE_CONFLICT", manual_review=True,
                              conflicts=tuple(conflicts))

        # --- classify disposition ---
        disposition = classify_disposition(journal_types, child_states, evidence)
        # approval-recovery gate §17: a resume (verify or prepare) needs a
        # still-valid single-use approval; recovery never mints a new one.
        would_resume = disposition in (
            RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY,
            RecoveryDisposition.SAFE_TO_RESUME_PREPARE,
        )
        if would_resume and (approval_consumed or approval_expired or approval_mismatch):
            return self._plan(evidence, journal_types,
                              RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
                              "APPROVAL_INVALID_FOR_RECOVERY", manual_review=True,
                              conflicts=("approval-not-valid-for-recovery",))
        gstate = global_state_from_children(child_states)
        self.store.journal.append("RECOVERY_STATE_CLASSIFIED",
                                  {"tx": self.tx_id, "disposition": disposition.value,
                                   "global": gstate})

        # --- terminal immutability ---
        if disposition == RecoveryDisposition.TERMINAL:
            self.store.journal.append("RECOVERY_COMPLETED", {"tx": self.tx_id})
            return self._plan(evidence, journal_types, disposition, "",
                              gstate=gstate, manual_review=False)

        return self._plan(evidence, journal_types, disposition, "",
                          gstate=gstate,
                          would_verify=disposition in (
                              RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY,
                              RecoveryDisposition.SAFE_TO_RESUME_PREPARE),
                          would_compensate=disposition in (
                              RecoveryDisposition.COMPENSATION_REQUIRED,),
                          manual_review=disposition in (
                              RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
                              RecoveryDisposition.UNKNOWN_RECOVERY_STATE),
                          conflicts=())

    def _plan(self, evidence, journal_types, disposition, violation, *,
              gstate="", would_verify=False, would_compensate=False,
              manual_review=False, conflicts=()) -> RecoveryPlan:
        cp = derive_crash_point(journal_types)
        if manual_review:
            self.store.journal.append("MANUAL_REVIEW_REQUIRED",
                                      {"tx": self.tx_id, "reason": violation or disposition.value})
        plan = RecoveryPlan(
            transaction_id=self.tx_id, recovery_generation=self.generation,
            global_tx_id=self.tx_id, semantic_key=self.semantic_key,
            disposition=disposition, crash_point=cp.value,
            violation=violation, would_verify=would_verify,
            would_compensate=would_compensate, manual_review=manual_review,
            conflicts=tuple(conflicts), refresh_after_monotonic=self.clock.monotonic() + 3600.0,
        )
        if would_compensate:
            self.store.journal.append("COMPENSATION_PLANNED", {"tx": self.tx_id})
        return plan

    @property
    def adapter_calls(self) -> int:
        return 0


__all__ = ["MultiServiceRecoveryCoordinator", "_MAX_AUTO_RECOVERY_GENERATIONS"]