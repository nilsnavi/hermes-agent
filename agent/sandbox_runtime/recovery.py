"""Bounded, deterministic crash recovery from validated durable evidence."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from .events import emit


class CrashPoint(str, Enum):
    FAIL_AFTER_PREFLIGHT = "FAIL_AFTER_PREFLIGHT"
    FAIL_AFTER_BACKUP = "FAIL_AFTER_BACKUP"
    FAIL_AFTER_LOCK = "FAIL_AFTER_LOCK"
    FAIL_BEFORE_EXECUTE = "FAIL_BEFORE_EXECUTE"
    FAIL_DURING_EXECUTE = "FAIL_DURING_EXECUTE"
    FAIL_AFTER_EXECUTE = "FAIL_AFTER_EXECUTE"
    FAIL_BEFORE_VERIFY = "FAIL_BEFORE_VERIFY"
    FAIL_DURING_VERIFY = "FAIL_DURING_VERIFY"
    FAIL_AFTER_VERIFY = "FAIL_AFTER_VERIFY"
    FAIL_DURING_HEALTH = "FAIL_DURING_HEALTH"
    FAIL_BEFORE_COMMIT = "FAIL_BEFORE_COMMIT"
    FAIL_DURING_ROLLBACK = "FAIL_DURING_ROLLBACK"
    CRASH_AFTER_EXECUTE = "CRASH_AFTER_EXECUTE"


class RecoveryDisposition(str, Enum):
    SAFE_TO_ROLLBACK = "SAFE_TO_ROLLBACK"
    SAFE_TO_CONTINUE_VERIFY = "SAFE_TO_CONTINUE_VERIFY"
    WAIT_FOR_LOCK = "WAIT_FOR_LOCK"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True)
class IncompleteTransaction:
    transaction_id: str
    idempotency_key: Optional[str]
    state: str
    disposition: RecoveryDisposition
    execution_started: bool
    execution_completed: bool
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    receipt: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "transaction_id": self.transaction_id, "txid": self.transaction_id,
            "idempotency_key": self.idempotency_key, "state": self.state,
            "disposition": self.disposition.value,
            "execution_started": self.execution_started,
            "execution_completed": self.execution_completed,
            "started_at": self.started_at, "updated_at": self.updated_at,
            "receipt": self.receipt,
        }


_TERMINAL = {"COMMITTED", "ROLLED_BACK", "CANCELLED", "DENIED"}
_ROLLBACK_SAFE = {"PLANNED", "PREFLIGHT_OK", "WAITING_APPROVAL", "APPROVED",
                  "SNAPSHOT_CREATED", "PREFLIGHT_FAILED", "APPROVAL_DENIED",
                  "APPROVAL_EXPIRED", "BACKUP_FAILED", "LOCK_FAILED",
                  "EXECUTION_FAILED", "VERIFY_FAILED", "HEALTH_FAILED",
                  "ROLLBACK_REQUIRED"}
_VERIFY_SAFE = {"EXECUTED", "VERIFIED"}
_AMBIGUOUS = {"CREATED", "STARTED", "EXECUTING", "VERIFYING",
              "HEALTH_CHECKING", "ROLLING_BACK", "UNKNOWN_OUTCOME",
              "ROLLBACK_VERIFY_FAILED", "MANUAL_REVIEW_REQUIRED"}
_LIFECYCLE = ["PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED",
              "LOCK_ACQUIRED", "EXECUTING", "EXECUTED", "VERIFIED",
              "COMMITTED"]
_REQUIRED_BY_STATE = {
    "PLANNED": ("plan_id", "resolved_target", "operation", "resource_type", "planned_at"),
    "PREFLIGHT_OK": ("preflight_fingerprint", "preflight_at"),
    "APPROVED": ("approval_reference", "approved_at"),
    "SNAPSHOT_CREATED": ("snapshot_reference", "snapshot_at"),
    "LOCK_ACQUIRED": ("lock_proof", "locked_at"),
}
_LOCK_PROOF_FIELDS = ("lock_key", "transaction_id", "pid", "process_start",
                      "process_nonce", "resource_identity", "acquired_at", "ttl_s")


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def validate_transaction_invariants(tx: Dict[str, Any]) -> tuple[str, ...]:
    """Return deterministic invariant violations for durable recovery evidence."""
    errors: list[str] = []
    txid = tx.get("transaction_id") or tx.get("txid")
    if not txid:
        errors.append("missing transaction_id")
    if not tx.get("idempotency_key"):
        errors.append("missing idempotency_key")
    state = str(tx.get("state") or tx.get("status") or "")
    for field in ("run_id", "step_id", "request_id", "operation",
                  "resource_identity", "created_at", "updated_at"):
        if tx.get(field) in (None, ""):
            errors.append(f"missing {field}")
    for field in ("created_at", "updated_at"):
        if tx.get(field) and not _valid_timestamp(tx[field]):
            errors.append(f"invalid {field}")

    # Legacy journals predate the durable pre-execution chain.  Their terminal
    # receipts remain valid if the original execution/verify/health invariants
    # hold; new-format rows advertise themselves with planned_at.
    durable_lifecycle = bool(tx.get("planned_at"))
    if durable_lifecycle and (state in _LIFECYCLE or state == "ROLLED_BACK"):
        end = _LIFECYCLE.index(state) if state in _LIFECYCLE else len(_LIFECYCLE) - 2
        for lifecycle_state in _LIFECYCLE[:min(end, 4) + 1]:
            for field in _REQUIRED_BY_STATE.get(lifecycle_state, ()):
                if tx.get(field) in (None, "", {}):
                    errors.append(f"missing {field}")
                if field.endswith("_at") and tx.get(field) and not _valid_timestamp(tx[field]):
                    errors.append(f"invalid {field}")

    proof = tx.get("lock_proof")
    if (durable_lifecycle or proof is not None) and state in {
            "LOCK_ACQUIRED", "EXECUTING", "EXECUTED", "VERIFIED",
            "COMMITTED", "ROLLED_BACK"}:
        if not isinstance(proof, dict):
            errors.append("missing lock_proof")
        else:
            for field in _LOCK_PROOF_FIELDS:
                if proof.get(field) in (None, ""):
                    errors.append(f"missing lock_proof.{field}")
            if proof.get("transaction_id") != txid:
                errors.append("lock_proof transaction mismatch")

    status = str(tx.get("status") or "")
    if status == "COMMITTED" or state == "COMMITTED":
        for field in ("execution_receipt", "verification_receipt", "health_receipt"):
            if not isinstance(tx.get(field), dict):
                errors.append(f"missing {field}")
        if not tx.get("execution_completed"):
            errors.append("execution incomplete")
        if not tx.get("verified"):
            errors.append("verification incomplete")
        if tx.get("health_ok") is not True:
            errors.append("health incomplete")
        if not _valid_timestamp(tx.get("committed_at")):
            errors.append("invalid committed_at")
        if not _valid_timestamp(tx.get("completed_at")):
            errors.append("invalid completed_at")
    if status == "ROLLED_BACK" or state == "ROLLED_BACK":
        receipt = tx.get("rollback_receipt")
        if not isinstance(receipt, dict) or receipt.get("completed") is not True:
            errors.append("missing rollback_receipt")
        if not _valid_timestamp(tx.get("rolled_back_at")):
            errors.append("invalid rolled_back_at")
        if not _valid_timestamp(tx.get("completed_at")):
            errors.append("invalid completed_at")
    return tuple(sorted(set(errors)))


def disposition_for_state(state: object, *, execution_started: bool = False,
                          execution_completed: bool = False) -> RecoveryDisposition:
    value = state.value if hasattr(state, "value") else str(state)
    if value in _TERMINAL:
        return RecoveryDisposition.TERMINAL
    if execution_started and not execution_completed:
        return RecoveryDisposition.MANUAL_REVIEW_REQUIRED
    if value == "LOCK_ACQUIRED":
        return RecoveryDisposition.WAIT_FOR_LOCK
    if value in _VERIFY_SAFE:
        return RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY
    if value in _ROLLBACK_SAFE:
        return RecoveryDisposition.SAFE_TO_ROLLBACK
    return RecoveryDisposition.MANUAL_REVIEW_REQUIRED


def classify_incomplete(tx: Dict[str, Any]) -> str:
    if tx.get("tool_started") and not tx.get("tool_completed"):
        return "UNKNOWN_OUTCOME"
    if tx.get("execution_started") and not tx.get("execution_completed"):
        return "UNKNOWN_OUTCOME"
    return str(tx.get("state") or tx.get("status") or "UNKNOWN_OUTCOME")


def _read_latest_rows(sandbox_root) -> list[dict]:
    path = os.path.join(sandbox_root.root, ".txn", "transactions.jsonl")
    if not os.path.isfile(path):
        return []
    latest: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(row, dict):
                continue
            key = str(row.get("idempotency_key") or row.get("txid") or
                      row.get("transaction_id") or "")
            if key:
                latest[key] = row
    return list(latest.values())


def read_transaction_records(sandbox_root) -> list[dict]:
    return sorted(_read_latest_rows(sandbox_root),
                  key=lambda r: (str(r.get("transaction_id") or r.get("txid") or ""),
                                 str(r.get("idempotency_key") or "")))


def scan_incomplete_transactions(sandbox_root, *, limit: int = 100,
                                 events: Optional[list[dict]] = None,
                                 telemetry=None, run_id: str = "recovery") -> list[IncompleteTransaction]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0 or limit > 10000:
        raise ValueError("limit must be an integer between 0 and 10000")
    audit = events
    now = lambda: datetime.now(timezone.utc)
    if audit is not None:
        emit(audit, "SANDBOX_RECOVERY_SCAN_STARTED", run_id, now(), {"limit": limit})
    if telemetry is not None:
        telemetry.inc("sandbox_recovery_scans")

    rows: list[IncompleteTransaction] = []
    for tx in _read_latest_rows(sandbox_root):
        raw_state = str(tx.get("state") or tx.get("status") or "UNKNOWN_OUTCOME")
        execution_started = bool(tx.get("execution_started", tx.get("tool_started", False)))
        execution_completed = bool(tx.get("execution_completed", tx.get("tool_completed", False)))
        errors = validate_transaction_invariants(tx)
        state = classify_incomplete(tx)
        disposition = disposition_for_state(raw_state,
            execution_started=execution_started, execution_completed=execution_completed)
        if errors:
            disposition = RecoveryDisposition.MANUAL_REVIEW_REQUIRED
        unknown = state == "UNKNOWN_OUTCOME"
        if audit is not None and unknown:
            emit(audit, "SANDBOX_UNKNOWN_OUTCOME_DETECTED", run_id, now(),
                 {"transaction_id": tx.get("transaction_id") or tx.get("txid")})
        if telemetry is not None and unknown:
            telemetry.inc("sandbox_unknown_outcomes")
        if audit is not None:
            emit(audit, "SANDBOX_RECOVERY_CLASSIFIED", run_id, now(), {
                "transaction_id": tx.get("transaction_id") or tx.get("txid"),
                "disposition": disposition.value, "invariant_errors": list(errors)})
        if disposition is RecoveryDisposition.MANUAL_REVIEW_REQUIRED:
            if audit is not None:
                emit(audit, "SANDBOX_MANUAL_REVIEW_REQUIRED", run_id, now(),
                     {"transaction_id": tx.get("transaction_id") or tx.get("txid")})
            if telemetry is not None:
                telemetry.inc("sandbox_manual_reviews")
        row = IncompleteTransaction(
            transaction_id=str(tx.get("transaction_id") or tx.get("txid") or ""),
            idempotency_key=tx.get("idempotency_key"), state=state,
            disposition=disposition, execution_started=execution_started,
            execution_completed=execution_completed, started_at=tx.get("started_at"),
            updated_at=tx.get("updated_at"), receipt=tx.get("receipt"))
        rows.append(row)

    rows = sorted(rows, key=lambda r: (r.transaction_id, r.idempotency_key or ""))[:limit]
    incomplete = sum(r.disposition is not RecoveryDisposition.TERMINAL for r in rows)
    if telemetry is not None:
        telemetry.inc("sandbox_incomplete_transactions", incomplete)
    if audit is not None:
        emit(audit, "SANDBOX_RECOVERY_SCAN_COMPLETED", run_id, now(),
             {"classified": len(rows), "incomplete": incomplete})
    return rows


def recover_transactions(sandbox_root, auto_retry: bool = False) -> List[Dict[str, Any]]:
    results = []
    for row in scan_incomplete_transactions(sandbox_root, limit=10000):
        if row.disposition is RecoveryDisposition.TERMINAL:
            continue
        verdict = "UNKNOWN_OUTCOME" if (row.execution_started and
                                         not row.execution_completed) else row.state
        results.append({
            "txid": row.transaction_id, "idempotency_key": row.idempotency_key,
            "verdict": verdict, "disposition": row.disposition.value,
            "manual_review_required": row.disposition is RecoveryDisposition.MANUAL_REVIEW_REQUIRED,
            "auto_retry": False,
        })
    return results
