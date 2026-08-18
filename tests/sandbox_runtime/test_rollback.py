"""Rollback — restore snapshot, verify rollback, never hide original failure (Sprint 1.3.5 §22/§43)."""

from __future__ import annotations

import os

import pytest

from tests.sandbox_runtime.conftest import make_request, read_text, write_text
from agent.sandbox_runtime.exceptions import RollbackFailed
from agent.sandbox_runtime.models import SandboxOperation
from agent.sandbox_runtime.rollback import RollbackManager
from agent.sandbox_runtime.snapshot import SnapshotManager


def test_rollback_restores_file_byte_for_byte(sandbox_root, mkfile, make_req):
    path = mkfile("data/rb1.txt", "ORIGINAL-CONTENT")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/rb1.txt",
                   expected_state="present")
    snap = SnapshotManager(sandbox_root).create("tx-rb1", req, resolved_target=path)
    write_text(path, "MUTATED-CONTENT-LONGER")
    rb = RollbackManager(sandbox_root)
    outcome = rb.rollback("tx-rb1", snap, resolved_target=path, original_failure="VERIFY_FAILED")
    assert outcome.status == "ROLLED_BACK"
    assert read_text(path) == "ORIGINAL-CONTENT"


def test_rollback_restores_permissions(sandbox_root, mkfile, make_req):
    path = mkfile("data/rb2.txt", "x")
    os.chmod(path, 0o640)
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/rb2.txt",
                   expected_state="present")
    snap = SnapshotManager(sandbox_root).create("tx-rb2", req, resolved_target=path)
    os.chmod(path, 0o777)
    rb = RollbackManager(sandbox_root)
    outcome = rb.rollback("tx-rb2", snap, resolved_target=path, original_failure="HEALTH_FAILED")
    assert (os.stat(path).st_mode & 0o777) == 0o640
    assert outcome.status == "ROLLED_BACK"


def test_rollback_restores_deleted_file(sandbox_root, mkfile, make_req):
    path = mkfile("data/rb3.txt", "KEEP-ME")
    req = make_req(operation=SandboxOperation.DELETE_FILE, target="data/rb3.txt",
                   expected_state="present")
    snap = SnapshotManager(sandbox_root).create("tx-rb3", req, resolved_target=path)
    os.remove(path)
    rb = RollbackManager(sandbox_root)
    outcome = rb.rollback("tx-rb3", snap, resolved_target=path, original_failure="EXECUTION_FAILED")
    assert read_text(path) == "KEEP-ME"
    assert outcome.status == "ROLLED_BACK"


def test_rollback_records_original_failure(sandbox_root, mkfile, make_req):
    path = mkfile("data/rb4.txt", "x")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/rb4.txt",
                   expected_state="present")
    snap = SnapshotManager(sandbox_root).create("tx-rb4", req, resolved_target=path)
    rb = RollbackManager(sandbox_root)
    outcome = rb.rollback("tx-rb4", snap, resolved_target=path,
                          original_failure="VERIFY_FAILED")
    assert outcome.original_failure == "VERIFY_FAILED"


def test_rollback_verify_failure_manual_review(sandbox_root, mkfile, make_req):
    path = mkfile("data/rb5.txt", "A")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/rb5.txt",
                   expected_state="present")
    snap = SnapshotManager(sandbox_root).create("tx-rb5", req, resolved_target=path)
    # corrupt the snapshot so restore cannot succeed
    backed = os.path.join(snap.dir, "target.bin")
    os.remove(backed)
    rb = RollbackManager(sandbox_root)
    outcome = rb.rollback("tx-rb5", snap, resolved_target=path,
                          original_failure="EXECUTION_FAILED")
    assert outcome.status == "ROLLBACK_VERIFY_FAILED"
    assert outcome.manual_review_required


def test_rollback_audit_contains_both_reasons(sandbox_root, mkfile, make_req):
    path = mkfile("data/rb6.txt", "x")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/rb6.txt",
                   expected_state="present")
    snap = SnapshotManager(sandbox_root).create("tx-rb6", req, resolved_target=path)
    rb = RollbackManager(sandbox_root)
    outcome = rb.rollback("tx-rb6", snap, resolved_target=path,
                          original_failure="EXECUTION_FAILED")
    assert "original_failure" in outcome.audit
    assert outcome.audit["original_failure"] == "EXECUTION_FAILED"
    assert outcome.audit["rollback_status"] == "ROLLED_BACK"


def test_rollback_missing_snapshot_fails_fast(sandbox_root, make_req):
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/rb7.txt",
                   expected_state="present")
    rb = RollbackManager(sandbox_root)
    with pytest.raises(RollbackFailed):
        rb.rollback("tx-nosnap", snapshot=None, resolved_target="/x",
                    original_failure="EXECUTION_FAILED")
