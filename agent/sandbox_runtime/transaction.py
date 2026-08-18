"""Transaction store — durable exactly-once receipts (Sprint 1.3.5 §12/§13/§24)."""

from __future__ import annotations

import json
import hashlib
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .exceptions import DuplicateAction, UnknownOperation, UnknownResource
from .models import ResourceType, SandboxMutationRequest, SandboxOperation

#: Known operations / resource types — anything else is DENY (§5/§6/§7).
KNOWN_OPERATIONS = {o.value for o in SandboxOperation}
KNOWN_RESOURCES = {r.value for r in ResourceType}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def assert_known_operation(op: str) -> None:
    if op not in KNOWN_OPERATIONS:
        raise UnknownOperation(f"unknown operation: {op!r}")


def assert_known_resource(resource: str) -> None:
    if resource not in KNOWN_RESOURCES:
        raise UnknownResource(f"unknown resource type: {resource!r}")


class TransactionStore:
    """Durable, append-only JSONL journal under ``.txn/``.

    Exactly-once (§13): UNIQUE on idempotency_key is enforced at the
    store level — record_started writes the STARTED marker once; a
    duplicate request returns the prior receipt (replay) instead of a
    second execution. Orphaned STARTED rows (no COMPLETED) are
    UNKNOWN_OUTCOME and never auto-retried.
    """

    def __init__(self, sandbox_root) -> None:
        self._dir = os.path.join(sandbox_root.root, ".txn")
        os.makedirs(self._dir, mode=0o700, exist_ok=True)
        self._lock = threading.Lock()
        self._rows: Dict[str, Dict] = {}
        self._load()

    def _path(self) -> str:
        return os.path.join(self._dir, "transactions.jsonl")

    def _claim_path(self, idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return os.path.join(self._dir, f"claim-{digest}.claim")

    def _load(self) -> None:
        path = self._path()
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = rec.get("idempotency_key")
                if key:
                    self._rows[key] = rec

    def _append(self, rec: Dict[str, Any]) -> None:
        path = self._path()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # ── lifecycle ──────────────────────────────────────────────────

    def _transition(self, req: SandboxMutationRequest, state: str,
                    fields: Optional[Dict[str, Any]] = None) -> None:
        """Append and publish one fsynced lifecycle transition."""
        with self._lock:
            rec = self._rows.get(req.idempotency_key)
            if rec is None:
                raise KeyError(f"no transaction for {req.idempotency_key}")
            updated_at = _now()
            updated = {**rec, **dict(fields or {}), "state": state,
                       "updated_at": updated_at, "event": state}
            self._append(updated)
            updated.pop("event", None)
            self._rows[req.idempotency_key] = updated

    def record_planned(self, req: SandboxMutationRequest, txid: str, *,
                       plan_id: str, resolved_target: str) -> None:
        """Claim idempotency and persist PLANNED before later side effects."""
        with self._lock:
            if req.idempotency_key in self._rows:
                raise DuplicateAction(f"duplicate action {req.idempotency_key}")
            claim_path = self._claim_path(req.idempotency_key)
            try:
                claim_fd = os.open(claim_path,
                                   os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                self._load()
                raise DuplicateAction(f"duplicate action {req.idempotency_key}")
            planned_at = _now()
            try:
                os.write(claim_fd, json.dumps({
                    "idempotency_key": req.idempotency_key,
                    "transaction_id": txid, "claimed_at": planned_at,
                }, sort_keys=True).encode("utf-8"))
                os.fsync(claim_fd)
            finally:
                os.close(claim_fd)
            rec = {
                "idempotency_key": req.idempotency_key,
                "request_id": req.request_id, "run_id": req.run_id,
                "step_id": req.step_id, "txid": txid,
                "transaction_id": txid, "status": "STARTED",
                "state": "PLANNED", "plan_id": plan_id,
                "resolved_target": resolved_target,
                "resource_identity": resolved_target,
                "operation": req.operation, "resource_type": req.resource_type,
                "target": req.target, "tool_started": False,
                "tool_completed": False, "execution_started": False,
                "execution_completed": False, "planned_at": planned_at,
                "created_at": planned_at, "started_at": planned_at,
                "updated_at": planned_at,
                "execution_receipt": None, "verification_receipt": None,
                "health_receipt": None, "rollback_receipt": None,
            }
            try:
                self._append(rec)
            except BaseException:
                try:
                    os.unlink(claim_path)
                except OSError:
                    pass
                raise
            self._rows[req.idempotency_key] = rec

    def record_preflight(self, req: SandboxMutationRequest, *,
                         fingerprint: str) -> None:
        self._transition(req, "PREFLIGHT_OK", {
            "preflight_fingerprint": fingerprint, "preflight_at": _now()})

    def record_approved(self, req: SandboxMutationRequest, *,
                        approval_reference: str) -> None:
        self._transition(req, "APPROVED", {
            "approval_reference": approval_reference, "approved_at": _now()})

    def record_snapshot(self, req: SandboxMutationRequest, *,
                        snapshot_reference: str) -> None:
        self._transition(req, "SNAPSHOT_CREATED", {
            "snapshot_reference": snapshot_reference, "backup_recorded": True,
            "backup_receipt_at": _now(), "snapshot_at": _now()})

    def record_lock_acquired(self, req: SandboxMutationRequest, *,
                             lock_proof: Dict[str, Any]) -> None:
        self._transition(req, "LOCK_ACQUIRED", {
            "lock_proof": dict(lock_proof),
            "resource_identity": lock_proof.get("resource_identity"),
            "locked_at": _now()})

    def record_execution_started(self, req: SandboxMutationRequest) -> None:
        at = _now()
        self._transition(req, "EXECUTING", {
            "tool_started": True, "execution_started": True,
            "execution_receipt": {"started": True, "at": at},
            "execution_started_at": at})

    def record_started(self, req: SandboxMutationRequest,
                       txid: str,
                       context: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            existing = self._rows.get(req.idempotency_key)
            if existing is not None and existing.get("transaction_id") == txid:
                at = _now()
                updated = {**existing, "state": "EXECUTING",
                           "tool_started": True, "execution_started": True,
                           "execution_receipt": {"started": True, "at": at},
                           "execution_started_at": at, "updated_at": at,
                           "event": "EXECUTING"}
                self._append(updated)
                updated.pop("event", None)
                self._rows[req.idempotency_key] = updated
                return
            if req.idempotency_key in self._rows:
                prior = self._rows[req.idempotency_key]
                if prior.get("status") in ("COMMITTED", "ROLLED_BACK",
                                           "UNKNOWN_OUTCOME",
                                           "MANUAL_REVIEW_REQUIRED"):
                    return  # replay path returns prior result
                raise DuplicateAction(
                    f"duplicate in-flight action {req.idempotency_key}")
            claim_path = self._claim_path(req.idempotency_key)
            try:
                claim_fd = os.open(claim_path,
                                   os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                # Another process/store instance owns the exactly-once claim.
                self._load()
                prior = self._rows.get(req.idempotency_key)
                if prior and prior.get("status") in (
                        "COMMITTED", "ROLLED_BACK", "UNKNOWN_OUTCOME",
                        "MANUAL_REVIEW_REQUIRED"):
                    return
                raise DuplicateAction(
                    f"duplicate in-flight action {req.idempotency_key}")
            try:
                os.write(claim_fd, json.dumps({
                    "idempotency_key": req.idempotency_key,
                    "transaction_id": txid,
                    "claimed_at": _now(),
                }, sort_keys=True).encode("utf-8"))
                os.fsync(claim_fd)
            finally:
                os.close(claim_fd)
            context = dict(context or {})
            created_at = _now()
            rec = {
                "idempotency_key": req.idempotency_key,
                "request_id": req.request_id,
                "run_id": req.run_id,
                "step_id": req.step_id,
                "txid": txid,
                "transaction_id": txid,
                "status": "STARTED",
                "state": "CREATED",
                "tool_started": True,
                "tool_completed": False,
                "execution_started": True,
                "execution_completed": False,
                "created_at": created_at,
                "started_at": created_at,
                "updated_at": created_at,
                "operation": req.operation,
                "resource_type": req.resource_type,
                "target": req.target,
                "resource_identity": context.get("resource_identity", req.target),
                "preflight_fingerprint": context.get("preflight_fingerprint"),
                "snapshot_reference": context.get("snapshot_reference"),
                "approval_reference": context.get("approval_reference", req.approval_id),
                "execution_receipt": {"started": True, "at": _now()},
                "verification_receipt": None,
                "health_receipt": None,
                "rollback_receipt": None,
            }
            try:
                self._append(rec)
            except BaseException:
                try:
                    os.unlink(claim_path)
                except OSError:
                    pass
                raise
            self._rows[req.idempotency_key] = rec

    def record_completed(self, req: SandboxMutationRequest, status: str,
                         receipt: Dict[str, Any],
                         require_backup: bool = False,
                         require_verification: bool = False,
                         require_health: bool = False) -> None:
        with self._lock:
            rec = self._rows.get(req.idempotency_key)
            if rec is None:
                raise KeyError(
                    f"no started transaction for {req.idempotency_key}")
            if status == "ROLLED_BACK":
                raise DuplicateAction(
                    "rollback requires atomic record_rolled_back receipt")
            if status == "COMMITTED":
                if not rec.get("backup_recorded"):
                    raise DuplicateAction(
                        "commit without trusted snapshot — pipeline invariant")
                if not rec.get("execution_completed"):
                    raise DuplicateAction(
                        "commit without execution receipt — pipeline invariant")
                if not rec.get("verified"):
                    raise DuplicateAction(
                        "commit without verification — pipeline invariant")
                if rec.get("health_ok") is not True:
                    raise DuplicateAction(
                        "commit without successful health — pipeline invariant")
            if require_backup and not rec.get("backup_recorded"):
                raise DuplicateAction(
                    "mutation without backup — pipeline invariant")
            if require_verification and not rec.get("verified"):
                raise DuplicateAction(
                    "commit without verification — pipeline invariant")
            if require_health and rec.get("health_ok") is not True:
                raise DuplicateAction(
                    "commit without successful health — pipeline invariant")
            # Atomic commit invariant: status and receipt are one fsynced
            # append. In-memory state is published only after durability.
            completed = {**rec, "status": status, "state": status,
                         "tool_completed": True,
                         "execution_completed": True,
                         "receipt": dict(receipt), "updated_at": _now(),
                         "completed_at": _now(), "event": "COMPLETED"}
            if status == "COMMITTED":
                completed["committed_at"] = _now()
            self._append(completed)
            completed.pop("event", None)
            self._rows[req.idempotency_key] = completed

    def record_executed(self, req: SandboxMutationRequest,
                        receipt: Dict[str, Any]) -> None:
        """Durably mark a returned adapter call before verification."""
        with self._lock:
            rec = self._rows.get(req.idempotency_key)
            if rec is None:
                raise KeyError(f"no started transaction for {req.idempotency_key}")
            executed_at = _now()
            updated = {**rec, "execution_completed": True,
                       "execution_receipt": {**dict(receipt),
                                             "completed": True,
                                             "at": executed_at},
                       "state": "EXECUTED", "updated_at": executed_at,
                       "event": "EXECUTED"}
            self._append(updated)
            updated.pop("event", None)
            self._rows[req.idempotency_key] = updated

    def record_rolled_back(self, req: SandboxMutationRequest, *,
                           original_failure: str,
                           receipt: Dict[str, Any]) -> None:
        """Atomically persist terminal status and rollback evidence."""
        with self._lock:
            rec = self._rows.get(req.idempotency_key)
            if rec is None:
                raise KeyError(f"no transaction for {req.idempotency_key}")
            rolled_back_at = _now()
            rollback_receipt = {
                **dict(receipt), "original_failure": original_failure,
                "completed": True, "at": rolled_back_at,
            }
            completed = {
                **rec, "status": "ROLLED_BACK", "state": "ROLLED_BACK",
                "tool_completed": True, "rollback_receipt": rollback_receipt,
                "receipt": dict(receipt), "rolled_back_at": rolled_back_at,
                "completed_at": rolled_back_at, "updated_at": rolled_back_at,
                "event": "ROLLED_BACK",
            }
            self._append(completed)
            completed.pop("event", None)
            self._rows[req.idempotency_key] = completed

    def record_backup(self, req: SandboxMutationRequest) -> None:
        with self._lock:
            rec = self._rows.get(req.idempotency_key)
            if rec is None:
                return
            updated = {**rec, "backup_recorded": True,
                       "backup_receipt_at": _now(), "updated_at": _now(),
                       "event": "BACKUP"}
            self._append(updated)
            updated.pop("event", None)
            self._rows[req.idempotency_key] = updated

    def record_verified(self, req: SandboxMutationRequest) -> None:
        with self._lock:
            rec = self._rows.get(req.idempotency_key)
            if rec is None:
                return
            verified_at = _now()
            updated = {**rec, "verified": True,
                       "verification_receipt": {"ok": True, "at": verified_at},
                       "verification_receipt_at": verified_at,
                       "updated_at": verified_at, "event": "VERIFIED"}
            self._append(updated)
            updated.pop("event", None)
            self._rows[req.idempotency_key] = updated

    def record_health(self, req: SandboxMutationRequest, *, ok: bool) -> None:
        """Persist the independent health receipt before commit."""
        with self._lock:
            rec = self._rows.get(req.idempotency_key)
            if rec is None:
                raise KeyError(f"no started transaction for {req.idempotency_key}")
            health_at = _now()
            updated = {**rec, "health_ok": bool(ok),
                       "health_receipt": {"ok": bool(ok), "at": health_at},
                       "updated_at": health_at, "event": "HEALTH"}
            self._append(updated)
            updated.pop("event", None)
            self._rows[req.idempotency_key] = updated

    def record_unknown(self, req: SandboxMutationRequest,
                       reason: str) -> None:
        with self._lock:
            rec = self._rows.get(req.idempotency_key)
            if rec is None:
                rec = {
                    "idempotency_key": req.idempotency_key,
                    "request_id": req.request_id,
                    "run_id": req.run_id,
                    "txid": req.run_id,
                    "status": "UNKNOWN_OUTCOME",
                    "tool_started": True,
                    "tool_completed": False,
                }
                self._rows[req.idempotency_key] = rec
            updated = {**rec, "status": "UNKNOWN_OUTCOME",
                       "state": "UNKNOWN_OUTCOME", "reason": reason,
                       "updated_at": _now(), "event": "UNKNOWN"}
            self._append(updated)
            updated.pop("event", None)
            self._rows[req.idempotency_key] = updated

    # ── reads ──────────────────────────────────────────────────────

    def replay(self, req: SandboxMutationRequest,
               allow_inflight: bool = True) -> Optional[Dict[str, Any]]:
        """§13 — prior result for the same idempotency_key.

        A STARTED-without-COMPLETED receipt (crash) is surfaced as
        UNKNOWN_OUTCOME — it is never presented as success.
        """
        with self._lock:
            rec = self._rows.get(req.idempotency_key)
            if rec is None:
                return None
            if rec.get("status") == "STARTED" and not allow_inflight:
                raise DuplicateAction(
                    f"in-flight duplicate {req.idempotency_key}")
            out = dict(rec)
            if rec.get("tool_started") and not rec.get("tool_completed"):
                out["status"] = "UNKNOWN_OUTCOME"
            return out

    def find_orphaned(self) -> List[Dict[str, Any]]:
        """STARTED without COMPLETED — crash candidates."""
        with self._lock:
            return [dict(r) for r in self._rows.values()
                    if r.get("tool_started") and not r.get("tool_completed")]

    def find_started(self, req: SandboxMutationRequest) -> List[Dict]:
        with self._lock:
            return [dict(r) for r in self._rows.values()
                    if r.get("idempotency_key") == req.idempotency_key]

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._rows.values()]
