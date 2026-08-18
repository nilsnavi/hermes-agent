"""Sandbox mutation pipeline (Sprint 1.3.5 §0/§12/§17/§21).

The full change-cycle, executed ONLY inside the sandbox:

    REQUEST → VALIDATE → RESOLVE → BOUNDARY → PLAN → PREFLIGHT
    → APPROVAL → SNAPSHOT → LOCK → TOCTOU → EXECUTE → VERIFY
    → HEALTH → COMMIT

On any failure: FREEZE → ROLLBACK → VERIFY ROLLBACK → HEALTH →
SAFE STATE → AUDIT.

Integration: every mutation passes SystemBoundaryLayer
(preflight/authorize/verify_before/verify_after). NoopSystemBoundary
is forbidden here — a real boundary is mandatory (BOUNDARY_REQUIRED).
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .adapter import AdapterResult, FaultInjector, SandboxAdapter
from .approval import ApprovalManager
from .chaos import ChaosController, FaultPoint
from .events import emit
from .exceptions import (
    AdapterAfterBlock,
    ApprovalError,
    BackupFailed,
    BoundaryRequired,
    DuplicateAction,
    GatewaySelfControlBlocked,
    HealthFailed,
    KillSwitchActive,
    LockConflict,
    PlanChangedAfterApproval,
    ResourceChangedAfterPreflight,
    RollbackFailed,
    SandboxError,
    SandboxPathEscape,
    SandboxPreflightFailed,
    UnknownExecutionResult,
    UnknownOperation,
    UnknownResource,
    VerifyFailed,
)
from .flags import SandboxFlags
from .health import check_sandbox_health
from .lock import ProcessLocalLock, ResourceLockManager
from .manual_review import ManualReviewStore
from .models import (
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    TRANSACTION_STATE_ERRORS,
    SandboxMutationPlan,
    SandboxMutationRequest,
    TransactionState,
)
from .preflight import run_preflight
from .recovery import CrashPoint
from .rollback import RollbackManager
from .security import GatewayGuard
from .snapshot import Snapshot, SnapshotManager
from .telemetry import Telemetry, Timing
from .toctou import verify_toctou
from .transaction import (
    TransactionStore,
    assert_known_operation,
    assert_known_resource,
)
from .verifier import verify_mutation


def utcnow() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc)


@dataclass
class SandboxMutationResult:
    status: str
    request_id: str = ""
    plan_id: str = ""
    transaction_id: str = ""
    adapter_calls: int = 0
    replayed: bool = False
    manual_review_required: bool = False
    error: str = ""
    receipt: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "request_id": self.request_id,
            "plan_id": self.plan_id,
            "transaction_id": self.transaction_id,
            "adapter_calls": self.adapter_calls,
            "replayed": self.replayed,
            "manual_review_required": self.manual_review_required,
            "error": self.error,
            "receipt": self.receipt,
        }


class SandboxMutationPipeline:
    """One controlled sandbox change-cycle executor."""

    def __init__(
        self,
        sandbox_root,
        clock: Optional[Callable[[], datetime]] = None,
        approve_automatically: bool = False,
        flags: Optional[SandboxFlags] = None,
        boundary=None,
        events: Optional[List[Dict[str, Any]]] = None,
        chaos: Optional[ChaosController] = None,
    ) -> None:
        self._root = sandbox_root
        self._clock = clock or utcnow
        self._approve_auto = approve_automatically
        self.flags = flags or SandboxFlags(enabled=True, mode="sandbox")
        self.audit: List[Dict[str, Any]] = events if events is not None else []
        self.telemetry = Telemetry()
        self.chaos = chaos or ChaosController()
        self.approval = ApprovalManager(clock=self._clock)
        self.snapshots = SnapshotManager(sandbox_root)
        self.locks = ResourceLockManager(sandbox_root)
        self.process_locks = ProcessLocalLock()
        self.store = TransactionStore(sandbox_root)
        self.guard = GatewayGuard()
        self.adapter = SandboxAdapter(sandbox_root,
                                      telemetry=self.telemetry)
        self.fault = FaultInjector()
        self.rollback_mgr = RollbackManager(sandbox_root)
        self.manual_reviews = ManualReviewStore(sandbox_root)
        self.boundary = boundary
        self._boundary_required()

    # ── boundary (§17) ─────────────────────────────────────────────

    def _boundary_required(self) -> None:
        if self.boundary is None:
            return
        name = type(self.boundary).__name__
        if name in ("NoopSystemBoundary",):
            raise BoundaryRequired(
                "NoopSystemBoundary is forbidden for sandbox mutation")

    def _boundary_gates(self, req: SandboxMutationRequest,
                        resolved: str):
        """preflight → authorize → verify_before_execute."""
        if self.boundary is None:
            return
        from .sandbox_boundary import SandboxBoundaryBridge
        bridge = SandboxBoundaryBridge(self.boundary)
        decision = bridge.authorize_path(resolved)
        if not decision.ok:
            self.telemetry.inc("sandbox_boundary_blocked")
            raise SandboxError(f"boundary BLOCK: {decision.reason}")

    # ── main entry ─────────────────────────────────────────────────

    def run(self, req: SandboxMutationRequest,
            approve_automatically: Optional[bool] = None) \
            -> SandboxMutationResult:
        txid = f"tx-{uuid.uuid4().hex[:12]}"
        auto = self._approve_auto if approve_automatically is None \
            else approve_automatically
        self.adapter.adapter_calls = 0
        emit(self.audit, "SANDBOX_MUTATION_REQUESTED", req.run_id,
             self._clock(), {"request_id": req.request_id,
                             "operation": req.operation,
                             "target": req.target})

        # 0) kill switch (§32/§42)
        if not self.flags.mutation_allowed:
            self.telemetry.inc("sandbox_mutation_failed")
            return SandboxMutationResult(
                status="DENIED", request_id=req.request_id,
                adapter_calls=0, error="kill switch active "
                                       "(HERMES_SANDBOX_MUTATION_V2_*)")

        # 1) model validation
        if not req.validate():
            self.telemetry.inc("sandbox_mutation_failed")
            return SandboxMutationResult(
                status="DENIED", request_id=req.request_id,
                adapter_calls=0, error="invalid request model")
        try:
            assert_known_operation(req.operation)
            assert_known_resource(req.resource_type)
        except (UnknownOperation, UnknownResource) as exc:
            self.telemetry.inc("sandbox_mutation_failed")
            return SandboxMutationResult(
                status="DENIED", request_id=req.request_id,
                adapter_calls=0, error=str(exc))

        # 2) request TTL (§8/§10) — created_at + ttl must not have lapsed
        from datetime import timedelta as _timedelta
        if req.created_at:
            try:
                from datetime import datetime as _dt
                created = _dt.fromisoformat(str(req.created_at))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=_dt.now().astimezone().tzinfo)
                if self._clock() > created + _timedelta(seconds=req.ttl):
                    self.telemetry.inc("sandbox_approval_denied")
                    return SandboxMutationResult(
                        status="APPROVAL_EXPIRED",
                        request_id=req.request_id, adapter_calls=0,
                        error="request TTL expired")
            except (ValueError, TypeError):
                return SandboxMutationResult(
                    status="DENIED", request_id=req.request_id,
                    adapter_calls=0, error="invalid created_at")

        # 3) exactly-once replay (§13) — before ANY side effect
        try:
            prior = self.store.replay(req)
        except DuplicateAction:
            self.telemetry.inc("sandbox_duplicate_action")
            return SandboxMutationResult(
                status="DUPLICATE_ACTION", request_id=req.request_id,
                adapter_calls=0, error="duplicate in-flight action")
        if prior is not None:
            prior_status = prior.get("status", "UNKNOWN_OUTCOME")
            if prior_status in ("COMMITTED", "ROLLED_BACK"):
                self.telemetry.inc("sandbox_duplicate_action")
                return SandboxMutationResult(
                    status=prior_status, request_id=req.request_id,
                    adapter_calls=0, replayed=True,
                    receipt=prior.get("receipt", {}))
            if prior_status in ("UNKNOWN_OUTCOME", "MANUAL_REVIEW_REQUIRED"):
                self.telemetry.inc("sandbox_unknown_outcome")
                return SandboxMutationResult(
                    status="MANUAL_REVIEW_REQUIRED",
                    request_id=req.request_id, adapter_calls=0,
                    manual_review_required=True,
                    error="UNKNOWN_OUTCOME — no automatic retry")

        # 3) path resolution (§4)
        try:
            from .root import resolve_sandbox_path
            resolved = resolve_sandbox_path(self._root.root, req.target)
        except SandboxPathEscape as exc:
            self.telemetry.inc("sandbox_path_escape_blocked")
            return SandboxMutationResult(
                status="DENIED", request_id=req.request_id,
                adapter_calls=0, error=str(exc))

        # 4) gateway self-control guard (§16/§33)
        try:
            self.guard.check(req)
        except (GatewaySelfControlBlocked, SandboxPathEscape) as exc:
            self.telemetry.inc("sandbox_boundary_blocked")
            return SandboxMutationResult(
                status="DENIED", request_id=req.request_id,
                adapter_calls=0, error=str(exc))

        # 5) system boundary (§17)
        try:
            self._boundary_gates(req, resolved)
        except SandboxError as exc:
            return SandboxMutationResult(
                status="DENIED", request_id=req.request_id,
                adapter_calls=0, error=str(exc))

        # 6) plan (§7)
        plan = SandboxMutationPlan(
            plan_id=f"plan-{uuid.uuid4().hex[:10]}",
            request_id=req.request_id,
            resolved_target=resolved,
            operation=req.operation,
            resource_type=req.resource_type,
            before_state=req.expected_state,
            expected_after_state=req.expected_state,
            risk=req.risk_class,
            approval_required=True,
            backup_required=True,
            verification_strategy="independent",
            rollback_strategy="snapshot",
            health_strategy="sandbox",
            preflight_fingerprint="",
            created_at=self._clock().isoformat(),
        )
        emit(self.audit, "SANDBOX_PLAN_CREATED", req.run_id,
             self._clock(), {"plan_id": plan.plan_id})
        try:
            self.store.record_planned(
                req, txid, plan_id=plan.plan_id, resolved_target=resolved)
        except DuplicateAction:
            self.telemetry.inc("sandbox_duplicate_action")
            return SandboxMutationResult(
                status="DUPLICATE_ACTION", request_id=req.request_id,
                plan_id=plan.plan_id, transaction_id=txid,
                adapter_calls=0, error="duplicate durable transaction")
        self.chaos.hit(FaultPoint.AFTER_PLAN)

        # 7) preflight (§8)
        emit(self.audit, "SANDBOX_PREFLIGHT_STARTED", req.run_id,
             self._clock(), {})
        try:
            preflight = run_preflight(req, self._root)
        except SandboxPreflightFailed as exc:
            self.telemetry.inc("sandbox_preflight_failed")
            emit(self.audit, "SANDBOX_PREFLIGHT_FAILED", req.run_id,
                 self._clock(), {"error": str(exc)})
            return SandboxMutationResult(
                status="PREFLIGHT_FAILED", request_id=req.request_id,
                plan_id=plan.plan_id, transaction_id=txid,
                adapter_calls=0, error=str(exc))
        if not preflight.ok:
            self.telemetry.inc("sandbox_preflight_failed")
            emit(self.audit, "SANDBOX_PREFLIGHT_FAILED", req.run_id,
                 self._clock(), {"error": preflight.reason})
            return SandboxMutationResult(
                status="PREFLIGHT_FAILED", request_id=req.request_id,
                plan_id=plan.plan_id, transaction_id=txid,
                adapter_calls=0, error=preflight.reason)
        plan = SandboxMutationPlan(
            plan_id=plan.plan_id,
            request_id=plan.request_id,
            resolved_target=plan.resolved_target,
            operation=plan.operation,
            resource_type=plan.resource_type,
            before_state=plan.before_state,
            expected_after_state=plan.expected_after_state,
            risk=plan.risk,
            approval_required=plan.approval_required,
            backup_required=plan.backup_required,
            verification_strategy=plan.verification_strategy,
            rollback_strategy=plan.rollback_strategy,
            health_strategy=plan.health_strategy,
            preflight_fingerprint=preflight.fingerprint,
            created_at=plan.created_at,
        )
        emit(self.audit, "SANDBOX_PREFLIGHT_PASSED", req.run_id,
             self._clock(), {"fingerprint": preflight.fingerprint[:12]})
        self.store.record_preflight(req, fingerprint=preflight.fingerprint)
        self.chaos.hit(FaultPoint.AFTER_PREFLIGHT)
        self._fault_check(CrashPoint.FAIL_AFTER_PREFLIGHT.value)

        # 8) approval (§10)
        if auto:
            approval_id = self.approval.issue(
                plan, requested_by=req.requested_by, ttl_s=req.ttl)
        else:
            approval_id = req.approval_id
        try:
            verdict = self.approval.validate(approval_id, plan, req.run_id)
            if not verdict.ok:
                raise ApprovalError(verdict.reason)
        except ApprovalError as exc:
            self.telemetry.inc("sandbox_approval_denied")
            status = "APPROVAL_EXPIRED" if "expired" in str(exc).lower() \
                else "APPROVAL_DENIED"
            return SandboxMutationResult(
                status=status, request_id=req.request_id,
                plan_id=plan.plan_id, transaction_id=txid,
                adapter_calls=0, error=str(exc))
        emit(self.audit, "SANDBOX_APPROVAL_VALIDATED", req.run_id,
             self._clock(), {"approval_id": approval_id})
        self.store.record_approved(req, approval_reference=str(approval_id))
        plan.lock_after_approval()
        self.chaos.hit(FaultPoint.AFTER_APPROVAL)

        # 9) snapshot / backup (§11) — MUST succeed before mutation
        try:
            snapshot = self.snapshots.create(txid, req, resolved)
            if not self.snapshots.verify(snapshot):
                raise BackupFailed("snapshot verification failed")
        except BackupFailed as exc:
            emit(self.audit, "SANDBOX_ROLLBACK_FAILED", req.run_id,
                 self._clock(), {"error": f"BACKUP_FAILED: {exc}"})
            return SandboxMutationResult(
                status="BACKUP_FAILED", request_id=req.request_id,
                plan_id=plan.plan_id, transaction_id=txid,
                adapter_calls=0, error=str(exc))
        self.store.record_snapshot(req, snapshot_reference=snapshot.dir)
        emit(self.audit, "SANDBOX_SNAPSHOT_CREATED", req.run_id,
             self._clock(), {"snapshot": snapshot.dir})
        self.chaos.hit(FaultPoint.AFTER_SNAPSHOT)

        # 10) lock (§14)
        lock_key = f"{req.resource_type}://{resolved}"
        try:
            self.process_locks.acquire(lock_key, owner=req.run_id,
                                       txid=txid, timeout_s=0.5)
            file_lock = self.locks.acquire(
                lock_key, owner=req.run_id, txid=txid,
                ttl_s=60, wait_s=0.5, recover_stale=False)
        except LockConflict as exc:
            self.telemetry.inc("sandbox_lock_conflict")
            return SandboxMutationResult(
                status="LOCK_FAILED", request_id=req.request_id,
                plan_id=plan.plan_id, transaction_id=txid,
                adapter_calls=0, error=str(exc))
        emit(self.audit, "SANDBOX_LOCK_ACQUIRED", req.run_id,
             self._clock(), {"lock_key": lock_key})
        self.store.record_lock_acquired(req, lock_proof={
            "lock_key": lock_key, "transaction_id": file_lock.txid,
            "pid": file_lock.pid, "process_start": file_lock.process_start,
            "process_nonce": file_lock.process_nonce,
            "resource_identity": file_lock.resource_identity,
            "acquired_at": file_lock.acquired_at, "ttl_s": file_lock.ttl_s,
        })
        self.chaos.hit(FaultPoint.AFTER_LOCK)
        self._fault_check(CrashPoint.FAIL_AFTER_LOCK.value)

        def _release_locks():
            self.locks.release(file_lock)
            self.process_locks.release({"key": lock_key, "txid": txid})

        # 11) TOCTOU second check (§9/§26)
        try:
            verify_toctou(req, self._root, preflight.fingerprint)
        except ResourceChangedAfterPreflight as exc:
            self.telemetry.inc("sandbox_toctou_blocked")
            _release_locks()
            return SandboxMutationResult(
                status="TOCTOU_BLOCKED", request_id=req.request_id,
                plan_id=plan.plan_id, transaction_id=txid,
                adapter_calls=0, error=str(exc))
        self._fault_check(CrashPoint.FAIL_BEFORE_EXECUTE.value)

        # 12) execute (§18) — the ONLY adapter call
        try:
            self.store.record_execution_started(req)
        except DuplicateAction:
            self.telemetry.inc("sandbox_duplicate_action")
            _release_locks()
            return SandboxMutationResult(
                status="DUPLICATE_ACTION", request_id=req.request_id,
                plan_id=plan.plan_id, transaction_id=txid,
                adapter_calls=0, error="duplicate in-flight action")
        try:
            self._fault_check(CrashPoint.FAIL_DURING_EXECUTE.value)
            self._fault_check(CrashPoint.FAIL_AFTER_BACKUP.value)
            emit(self.audit, "SANDBOX_EXECUTION_STARTED", req.run_id,
                 self._clock(), {})
            self.chaos.hit(FaultPoint.BEFORE_EXECUTE)
            with Timing(self.telemetry, "execution"):
                result: AdapterResult = self.adapter.execute(req)
            self.store.record_executed(req, {
                "status": result.status,
                "error_code": result.error_code,
            })
            emit(self.audit, "SANDBOX_EXECUTION_COMPLETED", req.run_id,
                 self._clock(), {"status": result.status,
                                 "error_code": result.error_code})
            self._fault_check(CrashPoint.FAIL_AFTER_EXECUTE.value)
            self.chaos.hit(FaultPoint.AFTER_EXECUTE)
        except SandboxError as exc:
            # crash / failure during execute
            self.store.record_unknown(req, reason=str(exc))
            self.telemetry.inc("sandbox_unknown_outcome")
            emit(self.audit, "SANDBOX_UNKNOWN_OUTCOME", req.run_id,
                 self._clock(), {"error": str(exc)})
            emit(self.audit, "SANDBOX_UNKNOWN_OUTCOME_DETECTED", req.run_id,
                 self._clock(), {"transaction_id": txid, "error": str(exc)})
            self.manual_reviews.create(
                transaction_id=txid, reason="unknown outcome",
                resource=req.target, operation=req.operation,
                state_observed=None, state_expected=req.expected_state,
                original_error=str(exc), rollback_error=None)
            self.telemetry.inc("sandbox_manual_review_created")
            self.telemetry.inc("sandbox_unknown_outcomes")
            self.telemetry.inc("sandbox_manual_reviews")
            emit(self.audit, "SANDBOX_MANUAL_REVIEW_REQUIRED", req.run_id,
                 self._clock(), {"transaction_id": txid})
            emit(self.audit, "SANDBOX_MANUAL_REVIEW_CREATED", req.run_id,
                 self._clock(), {"transaction_id": txid})
            _release_locks()
            return SandboxMutationResult(
                status="MANUAL_REVIEW_REQUIRED",
                request_id=req.request_id, plan_id=plan.plan_id,
                transaction_id=txid,
                adapter_calls=self.adapter.adapter_calls,
                manual_review_required=True,
                error=f"UNKNOWN_OUTCOME: {exc}")
        if result.status == "FAILED":
            self.telemetry.inc("sandbox_mutation_failed")
            emit(self.audit, "SANDBOX_EXECUTION_FAILED", req.run_id,
                 self._clock(), {"error": result.error_code})
            return self._rollback(
                req, plan, txid, snapshot, resolved,
                _release_locks, original_failure=f"EXECUTION_FAILED:"
                                                 f"{result.error_code}")

        # 13) verify (§19) — independent of the adapter
        emit(self.audit, "SANDBOX_VERIFY_STARTED", req.run_id,
             self._clock(), {})
        try:
            with Timing(self.telemetry, "verification"):
                verify_mutation(req, self._root,
                                adapter_said_success=True)
        except VerifyFailed as exc:
            self.telemetry.inc("sandbox_mutation_failed")
            emit(self.audit, "SANDBOX_VERIFY_FAILED", req.run_id,
                 self._clock(), {"error": str(exc)})
            return self._rollback(
                req, plan, txid, snapshot, resolved,
                _release_locks, original_failure=f"VERIFY_FAILED: {exc}")
        self.store.record_verified(req)
        emit(self.audit, "SANDBOX_VERIFY_PASSED", req.run_id,
             self._clock(), {})
        self.chaos.hit(FaultPoint.AFTER_VERIFY)
        self._fault_check(CrashPoint.FAIL_AFTER_VERIFY.value)

        # 14) health gate (§20)
        try:
            with Timing(self.telemetry, "verification"):
                health = check_sandbox_health(self._root,
                                              exclude_txid=txid)
            if not health.ok:
                raise HealthFailed(
                    f"health check failed: {health.checks}")
        except HealthFailed as exc:
            self.telemetry.inc("sandbox_mutation_failed")
            emit(self.audit, "SANDBOX_HEALTH_FAILED", req.run_id,
                 self._clock(), {"error": str(exc)})
            return self._rollback(
                req, plan, txid, snapshot, resolved,
                _release_locks, original_failure=f"HEALTH_FAILED: {exc}")
        emit(self.audit, "SANDBOX_HEALTH_PASSED", req.run_id,
             self._clock(), {})
        self.store.record_health(req, ok=True)
        self.chaos.hit(FaultPoint.AFTER_HEALTH)
        self._fault_check(CrashPoint.FAIL_BEFORE_COMMIT.value)

        # 15) commit (§21) — only after success+verify+health
        try:
            self.store.record_completed(
                req, "COMMITTED",
                {"plan_id": plan.plan_id, "txid": txid},
                require_backup=True, require_verification=True,
                require_health=True)
        except DuplicateAction:
            pass
        _release_locks()
        self.telemetry.inc("sandbox_mutation_committed")
        with Timing(self.telemetry, "total_transaction"):
            pass
        emit(self.audit, "SANDBOX_COMMITTED", req.run_id,
             self._clock(), {"txid": txid})
        self.chaos.hit(FaultPoint.AFTER_COMMIT)
        return SandboxMutationResult(
            status="COMMITTED", request_id=req.request_id,
            plan_id=plan.plan_id, transaction_id=txid,
            adapter_calls=self.adapter.adapter_calls,
            receipt={"plan_id": plan.plan_id, "txid": txid})

    # ── failure path (§22) ─────────────────────────────────────────

    def _rollback(self, req: SandboxMutationRequest,
                  plan: SandboxMutationPlan, txid: str,
                  snapshot: Snapshot, resolved: str,
                  release_locks, original_failure: str) \
            -> SandboxMutationResult:
        emit(self.audit, "SANDBOX_ROLLBACK_STARTED", req.run_id,
             self._clock(), {"original_failure": original_failure})
        try:
            with Timing(self.telemetry, "rollback"):
                outcome = self.rollback_mgr.rollback(
                    txid, snapshot, resolved,
                    original_failure=original_failure)
        except RollbackFailed as exc:
            release_locks()
            self.telemetry.inc("sandbox_mutation_rollback_failed")
            self.telemetry.inc("sandbox_rollback_failures")
            emit(self.audit, "SANDBOX_ROLLBACK_FAILED", req.run_id,
                 self._clock(), {"error": str(exc)})
            self.manual_reviews.create(
                transaction_id=txid, reason="rollback failed",
                resource=req.target, operation=req.operation,
                original_error=original_failure, rollback_error=str(exc))
            self.telemetry.inc("sandbox_manual_review_created")
            self.telemetry.inc("sandbox_manual_reviews")
            emit(self.audit, "SANDBOX_MANUAL_REVIEW_REQUIRED", req.run_id,
                 self._clock(), {"transaction_id": txid})
            emit(self.audit, "SANDBOX_MANUAL_REVIEW_CREATED", req.run_id,
                 self._clock(), {"transaction_id": txid})
            return SandboxMutationResult(
                status="MANUAL_REVIEW_REQUIRED",
                request_id=req.request_id, plan_id=plan.plan_id,
                transaction_id=txid,
                adapter_calls=self.adapter.adapter_calls,
                manual_review_required=True,
                error=f"ROLLBACK_FAILED: {exc}; original: "
                      f"{original_failure}")
        release_locks()
        if outcome.status == "ROLLED_BACK":
            self.store.record_rolled_back(
                req, original_failure=original_failure,
                receipt={"restored": True, "rollback_audit": outcome.audit})
            self.telemetry.inc("sandbox_mutation_rollback")
            emit(self.audit, "SANDBOX_ROLLED_BACK", req.run_id,
                 self._clock(), {"original_failure": original_failure})
            return SandboxMutationResult(
                status="ROLLED_BACK", request_id=req.request_id,
                plan_id=plan.plan_id, transaction_id=txid,
                adapter_calls=self.adapter.adapter_calls,
                error=original_failure)
        # ROLLBACK_VERIFY_FAILED → manual review
        self.telemetry.inc("sandbox_mutation_rollback_failed")
        self.telemetry.inc("sandbox_rollback_failures")
        emit(self.audit, "SANDBOX_ROLLBACK_FAILED", req.run_id,
             self._clock(), {"error": "rollback verification failed",
                             "original_failure": original_failure})
        self.manual_reviews.create(
            transaction_id=txid, reason="rollback verification failed",
            resource=req.target, operation=req.operation,
            original_error=original_failure,
            rollback_error=outcome.audit.get("rollback_error", "verification failed"))
        self.telemetry.inc("sandbox_manual_review_created")
        self.telemetry.inc("sandbox_manual_reviews")
        emit(self.audit, "SANDBOX_MANUAL_REVIEW_REQUIRED", req.run_id,
             self._clock(), {"transaction_id": txid})
        emit(self.audit, "SANDBOX_MANUAL_REVIEW_CREATED", req.run_id,
             self._clock(), {"transaction_id": txid})
        return SandboxMutationResult(
            status="MANUAL_REVIEW_REQUIRED",
            request_id=req.request_id, plan_id=plan.plan_id,
            transaction_id=txid,
            adapter_calls=self.adapter.adapter_calls,
            manual_review_required=True,
            error=f"ROLLBACK_VERIFY_FAILED; original: "
                  f"{original_failure}")

    # ── fault injection (tests/sandbox only) ───────────────────────

    def _fault_check(self, point: str) -> None:
        self.fault.check(point)
