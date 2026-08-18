"""Durable lifecycle and recovery contract (gaps 1, 2, 7, 10, 11)."""
from __future__ import annotations

import json
import os

from agent.sandbox_runtime.pipeline import SandboxMutationPipeline
from agent.sandbox_runtime.recovery import (
    RecoveryDisposition,
    scan_incomplete_transactions,
    validate_transaction_invariants,
)
from agent.sandbox_runtime.telemetry import Telemetry
from agent.sandbox_runtime.transaction import TransactionStore
from tests.sandbox_runtime.conftest import make_request


def _journal_rows(store: TransactionStore) -> list[dict]:
    with open(store._path(), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _advance_to_lock(store: TransactionStore, req, *, txid="tx-lock") -> None:
    store.record_planned(req, txid, plan_id="plan-1", resolved_target=req.target)
    store.record_preflight(req, fingerprint="fingerprint-1")
    store.record_approved(req, approval_reference="approval-1")
    store.record_snapshot(req, snapshot_reference="snapshot-1")
    store.record_lock_acquired(req, lock_proof={
        "lock_key": f"FILE://{req.target}",
        "transaction_id": txid,
        "pid": 123,
        "process_start": "456",
        "process_nonce": "nonce-1",
        "resource_identity": f"FILE://{req.target}",
        "acquired_at": 100.0,
        "ttl_s": 60.0,
    })


def test_pre_execution_lifecycle_is_durable_with_required_evidence(sandbox_root):
    store = TransactionStore(sandbox_root)
    req = make_request(idempotency_key="durable-lifecycle")
    _advance_to_lock(store, req)

    rows = _journal_rows(store)
    states = [row["state"] for row in rows]
    assert states == [
        "PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED",
        "LOCK_ACQUIRED",
    ]
    latest = rows[-1]
    assert latest["plan_id"] == "plan-1"
    assert latest["preflight_fingerprint"] == "fingerprint-1"
    assert latest["approval_reference"] == "approval-1"
    assert latest["snapshot_reference"] == "snapshot-1"
    assert latest["lock_proof"]["process_nonce"] == "nonce-1"
    for field in (
        "transaction_id", "run_id", "step_id", "request_id",
        "idempotency_key", "state", "operation", "resource_identity",
        "preflight_fingerprint", "snapshot_reference", "approval_reference",
        "execution_receipt", "verification_receipt", "health_receipt",
        "rollback_receipt", "created_at", "updated_at",
        "planned_at", "preflight_at", "approved_at", "snapshot_at",
        "locked_at",
    ):
        assert field in latest
    for field in ("created_at", "updated_at", "planned_at", "preflight_at",
                  "approved_at", "snapshot_at", "locked_at"):
        assert latest[field]


def test_valid_lock_proof_waits_but_incomplete_lock_proof_requires_review(sandbox_root):
    valid = TransactionStore(sandbox_root)
    req = make_request(idempotency_key="valid-lock")
    _advance_to_lock(valid, req, txid="tx-valid-lock")

    forged = make_request(idempotency_key="forged-lock")
    valid.record_planned(forged, "tx-forged-lock", plan_id="plan-2", resolved_target=forged.target)
    valid.record_preflight(forged, fingerprint="fp")
    valid.record_approved(forged, approval_reference="approval")
    valid.record_snapshot(forged, snapshot_reference="snapshot")
    valid.record_lock_acquired(forged, lock_proof={"transaction_id": "tx-forged-lock"})

    by_id = {row.transaction_id: row for row in scan_incomplete_transactions(sandbox_root)}
    assert by_id["tx-valid-lock"].disposition is RecoveryDisposition.WAIT_FOR_LOCK
    assert by_id["tx-forged-lock"].disposition is RecoveryDisposition.MANUAL_REVIEW_REQUIRED


def test_terminal_classification_requires_complete_validated_receipts_and_is_read_only(sandbox_root):
    store = TransactionStore(sandbox_root)
    valid_req = make_request(idempotency_key="valid-terminal")
    _advance_to_lock(store, valid_req, txid="tx-valid-terminal")
    store.record_execution_started(valid_req)
    store.record_executed(valid_req, {"ok": True})
    store.record_verified(valid_req)
    store.record_health(valid_req, ok=True)
    store.record_completed(valid_req, "COMMITTED", {"ok": True})

    forged_req = make_request(idempotency_key="forged-terminal")
    store.record_planned(forged_req, "tx-forged-terminal", plan_id="plan-x", resolved_target=forged_req.target)
    forged = {**store.replay(forged_req), "status": "COMMITTED", "state": "COMMITTED",
              "tool_completed": True, "completed_at": "not-a-timestamp"}
    store._append(forged)

    before = open(store._path(), "rb").read()
    rows = {row.transaction_id: row for row in scan_incomplete_transactions(sandbox_root)}
    after = open(store._path(), "rb").read()
    assert rows["tx-valid-terminal"].disposition is RecoveryDisposition.TERMINAL
    assert rows["tx-forged-terminal"].disposition is RecoveryDisposition.MANUAL_REVIEW_REQUIRED
    assert before == after


def test_rolled_back_receipt_is_atomic_reopenable_and_replayed(sandbox_root, monkeypatch):
    store = TransactionStore(sandbox_root)
    req = make_request(idempotency_key="durable-rollback")
    _advance_to_lock(store, req, txid="tx-rollback")
    store.record_execution_started(req)
    store.record_executed(req, {"status": "FAILED"})

    original_append = store._append
    monkeypatch.setattr(store, "_append", lambda row: (_ for _ in ()).throw(OSError("full")))
    try:
        try:
            store.record_rolled_back(req, original_failure="EXECUTION_FAILED",
                                     receipt={"restored": True})
        except OSError:
            pass
        assert store.replay(req)["status"] == "UNKNOWN_OUTCOME"
        assert store.all()[0]["status"] == "STARTED"
    finally:
        monkeypatch.setattr(store, "_append", original_append)

    store.record_rolled_back(req, original_failure="EXECUTION_FAILED", receipt={"restored": True})

    reopened = TransactionStore(sandbox_root)
    replay = reopened.replay(req)
    assert replay["status"] == "ROLLED_BACK"
    assert replay["rollback_receipt"]["restored"] is True
    assert replay["rollback_receipt"]["original_failure"] == "EXECUTION_FAILED"
    assert replay["rolled_back_at"]
    assert validate_transaction_invariants(replay) == ()


def test_generic_completion_cannot_forge_rolled_back_terminal(sandbox_root):
    store = TransactionStore(sandbox_root)
    req = make_request(idempotency_key="forged-rollback-api")
    store.record_started(req, "tx-forged-rollback-api")
    try:
        store.record_completed(req, "ROLLED_BACK", {"restored": True})
    except Exception:
        pass
    else:
        raise AssertionError("generic completion accepted rollback without receipt")


def test_recovery_scan_emits_and_counts_actual_classifications(sandbox_root):
    store = TransactionStore(sandbox_root)
    req = make_request(idempotency_key="scan-unknown")
    store.record_started(req, "tx-unknown")
    events: list[dict] = []
    telemetry = Telemetry()

    rows = scan_incomplete_transactions(
        sandbox_root, events=events, telemetry=telemetry, run_id="recovery-run")

    assert rows[0].disposition is RecoveryDisposition.MANUAL_REVIEW_REQUIRED
    types = [event["event_type"] for event in events]
    assert types == [
        "SANDBOX_RECOVERY_SCAN_STARTED",
        "SANDBOX_UNKNOWN_OUTCOME_DETECTED",
        "SANDBOX_RECOVERY_CLASSIFIED",
        "SANDBOX_MANUAL_REVIEW_REQUIRED",
        "SANDBOX_RECOVERY_SCAN_COMPLETED",
    ]
    counters = telemetry.counters()
    assert counters["sandbox_recovery_scans"] == 1
    assert counters["sandbox_incomplete_transactions"] == 1
    assert counters["sandbox_unknown_outcomes"] == 1
    assert counters["sandbox_manual_reviews"] == 1


def test_pipeline_emits_execution_completed_and_persists_all_lifecycle_states(sandbox_root):
    pipe = SandboxMutationPipeline(sandbox_root, approve_automatically=True)
    req = make_request(idempotency_key="pipeline-lifecycle", arguments={"content": "ok"})

    result = pipe.run(req)

    assert result.status == "COMMITTED"
    assert "SANDBOX_EXECUTION_COMPLETED" in [event["event_type"] for event in pipe.audit]
    states = [row["state"] for row in _journal_rows(pipe.store)]
    for state in ("PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED", "LOCK_ACQUIRED"):
        assert state in states
