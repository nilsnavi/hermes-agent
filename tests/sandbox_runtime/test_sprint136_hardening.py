"""Sprint 1.3.6 deterministic recovery hardening matrices."""
from __future__ import annotations

import errno
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.sandbox_runtime.cli import main as cli_main
from agent.sandbox_runtime.errors import CanonicalErrorCode, normalize_exception
from agent.sandbox_runtime.reconciliation import ReconciliationOutcome, reconcile_state
from agent.sandbox_runtime.recovery import RecoveryDisposition, scan_incomplete_transactions
from agent.sandbox_runtime.snapshot import SnapshotManager
from agent.sandbox_runtime.transaction import TransactionStore
from tests.sandbox_runtime.conftest import make_request


# C1-C10: real child-process death leaves a durable receipt and recovery is read-only.
@pytest.mark.parametrize("crash_index", range(1, 11))
def test_c1_c10_process_death_is_never_reexecuted(sandbox_root, crash_index):
    code = """
import os,sys
from agent.sandbox_runtime.root import SandboxRoot
from agent.sandbox_runtime.transaction import TransactionStore
from tests.sandbox_runtime.conftest import make_request
root=SandboxRoot(sys.argv[1])
store=TransactionStore(root)
store.record_started(make_request(idempotency_key='crash-'+sys.argv[2]), 'tx-'+sys.argv[2])
os._exit(70+int(sys.argv[2]))
"""
    child = subprocess.run([sys.executable, "-c", code, sandbox_root.root,
                            str(crash_index)], check=False)
    assert child.returncode == 70 + crash_index
    journal = os.path.join(sandbox_root.root, ".txn", "transactions.jsonl")
    before = open(journal, "rb").read()
    rows = scan_incomplete_transactions(sandbox_root, limit=100)
    after = open(journal, "rb").read()
    row = next(r for r in rows if r.transaction_id == f"tx-{crash_index}")
    assert row.disposition is RecoveryDisposition.MANUAL_REVIEW_REQUIRED
    assert before == after


# R1-R10: deterministic, pure reconciliation matrix.
@pytest.mark.parametrize("before,after,observed,outcome", [
    ("a", "b", "a", ReconciliationOutcome.UNCHANGED),
    ("a", "b", "b", ReconciliationOutcome.APPLIED),
    ("a", "after", "aft", ReconciliationOutcome.PARTIALLY_APPLIED),
    (b"a", b"after", b"af", ReconciliationOutcome.PARTIALLY_APPLIED),
    ("a", "b", "c", ReconciliationOutcome.DIVERGED),
    ("", "x", None, ReconciliationOutcome.UNKNOWN),
    ({"x": 1}, {"x": 2}, {"x": 1}, ReconciliationOutcome.UNCHANGED),
    ({"x": 1}, {"x": 2}, {"x": 2}, ReconciliationOutcome.APPLIED),
    (1, 2, 3, ReconciliationOutcome.DIVERGED),
    (False, True, None, ReconciliationOutcome.UNKNOWN),
])
def test_r1_r10_read_only_reconciliation(before, after, observed, outcome):
    assert reconcile_state(before, after, observed) is outcome


def test_eperm_has_canonical_permission_taxonomy():
    assert normalize_exception(OSError(errno.EPERM, "raw secret")).code is CanonicalErrorCode.PERMISSION_DENIED


def test_failed_commit_append_does_not_publish_in_memory(sandbox_root, monkeypatch):
    store = TransactionStore(sandbox_root)
    req = make_request(idempotency_key="atomic-commit")
    store.record_started(req, "tx-atomic")
    store.record_backup(req)
    store.record_executed(req, {"ok": True})
    store.record_verified(req)
    store.record_health(req, ok=True)
    monkeypatch.setattr(store, "_append", lambda row: (_ for _ in ()).throw(OSError(errno.ENOSPC, "full")))
    with pytest.raises(OSError):
        store.record_completed(req, "COMMITTED", {"ok": True})
    assert store.replay(req)["status"] == "UNKNOWN_OUTCOME"


def test_commit_requires_execution_verification_and_health_receipts(sandbox_root):
    store = TransactionStore(sandbox_root)
    req = make_request(idempotency_key="commit-invariants")
    store.record_started(req, "tx-invariants")
    store.record_backup(req)
    # COMMITTED is invalid even when caller omits optional require_* flags.
    with pytest.raises(Exception):
        store.record_completed(req, "COMMITTED", {"ok": True})
    store.record_executed(req, {"adapter": "sandbox", "ok": True})
    with pytest.raises(Exception):
        store.record_completed(req, "COMMITTED", {"ok": True})
    store.record_verified(req)
    with pytest.raises(Exception):
        store.record_completed(req, "COMMITTED", {"ok": True})
    store.record_health(req, ok=True)
    store.record_completed(req, "COMMITTED", {"ok": True})
    row = store.replay(req)
    assert row["status"] == "COMMITTED"
    assert row["execution_completed"] is True
    assert row["verified"] is True
    assert row["health_ok"] is True


def test_expired_lock_without_durable_proofs_is_ambiguous(sandbox_root):
    import json, os
    from agent.sandbox_runtime.exceptions import LockStaleRecovered
    from agent.sandbox_runtime.lock import ResourceLockManager
    manager = ResourceLockManager(sandbox_root)
    path = manager._lock_path("ambiguous")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"txid": "unknown-owner"}, fh)
    os.utime(path, (0, 0))
    with pytest.raises(Exception) as exc:
        manager.acquire("ambiguous", "new-owner", "tx-new",
                        ttl_s=1, wait_s=0, recover_stale=True)
    assert not isinstance(exc.value, LockStaleRecovered)


def test_required_telemetry_and_event_vocabulary_is_stable():
    from agent.sandbox_runtime.events import SANDBOX_EVENTS
    from agent.sandbox_runtime.telemetry import COUNTERS
    assert {
        "SANDBOX_PROCESS_CRASH_DETECTED", "SANDBOX_RECOVERY_SCAN_STARTED",
        "SANDBOX_RECOVERY_SCAN_COMPLETED", "SANDBOX_RECOVERY_CLASSIFIED",
        "SANDBOX_UNKNOWN_OUTCOME_DETECTED", "SANDBOX_STALE_LOCK_DETECTED",
        "SANDBOX_STALE_LOCK_RECOVERED", "SANDBOX_SNAPSHOT_INVALID",
        "SANDBOX_RECONCILIATION_STARTED", "SANDBOX_RECONCILIATION_COMPLETED",
        "SANDBOX_MANUAL_REVIEW_CREATED",
    }.issubset(set(SANDBOX_EVENTS))
    assert {
        "sandbox_recovery_scans", "sandbox_incomplete_transactions",
        "sandbox_unknown_outcomes", "sandbox_recovered_transactions",
        "sandbox_manual_reviews", "sandbox_stale_locks",
        "sandbox_lock_recoveries", "sandbox_snapshot_corruptions",
        "sandbox_rollback_failures", "sandbox_crash_recoveries",
    }.issubset(set(COUNTERS))


def test_recovery_cli_commands_are_read_only(sandbox_root, capsys):
    store = TransactionStore(sandbox_root)
    store.record_started(make_request(idempotency_key="cli-incomplete"), "tx-cli")
    journal = store._path()
    before = open(journal, "rb").read()
    assert cli_main(["--root", sandbox_root.root, "incomplete"]) == 0
    assert cli_main(["--root", sandbox_root.root, "recovery-status"]) == 0
    assert cli_main(["--root", sandbox_root.root, "manual-reviews"]) == 0
    assert open(journal, "rb").read() == before
    assert "tx-cli" in capsys.readouterr().out


def test_snapshot_checksum_rewrite_cannot_forge_authenticity(sandbox_root):
    target = os.path.join(sandbox_root.root, "data", "auth.txt")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    open(target, "wb").write(b"before")
    req = make_request(target="data/auth.txt", expected_state="present")
    mgr = SnapshotManager(sandbox_root)
    snap = mgr.create("tx-auth", req, target)
    content = os.path.join(snap.dir, "target.bin")
    manifest_path = os.path.join(snap.dir, "manifest.json")
    open(content, "wb").write(b"forged")
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    manifest["files"]["target.bin"]["sha256"] = hashlib.sha256(b"forged").hexdigest()
    open(manifest_path, "w", encoding="utf-8").write(json.dumps(manifest))
    names = ["target.bin", "perms.json", "manifest.json"]
    lines = []
    for name in names:
        data = open(os.path.join(snap.dir, name), "rb").read()
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
    open(snap.sha256sums, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    assert not mgr.validate_for(snap, "tx-auth", target)


def test_concurrent_store_instances_claim_idempotency_once(sandbox_root):
    stores = [TransactionStore(sandbox_root) for _ in range(20)]
    req = make_request(idempotency_key="concurrent-claim")

    def start(index):
        try:
            stores[index].record_started(req, f"tx-{index}")
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(start, range(20)))
    assert sum(results) == 1
