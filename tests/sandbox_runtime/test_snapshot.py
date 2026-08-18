"""Snapshot / backup — per-operation backup BEFORE mutation (Sprint 1.3.5 §11)."""

from __future__ import annotations

import hashlib
import os

import pytest

from tests.sandbox_runtime.conftest import make_request, read_text, write_text
from agent.sandbox_runtime.exceptions import BackupFailed
from agent.sandbox_runtime.models import SandboxOperation
from agent.sandbox_runtime.snapshot import SnapshotManager


def test_snapshot_created_before_mutation(sandbox_root, mkfile, make_req):
    path = mkfile("data/keep.txt", "original")
    os.chmod(path, 0o640)
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/keep.txt",
                   expected_state="present")
    mgr = SnapshotManager(sandbox_root)
    snap = mgr.create("tx-1", req, resolved_target=path)
    assert os.path.isdir(snap.dir)
    assert os.path.exists(os.path.join(snap.dir, "manifest.json"))
    assert os.path.exists(os.path.join(snap.dir, "SHA256SUMS"))


def test_snapshot_contains_original_content(sandbox_root, mkfile, make_req):
    path = mkfile("data/keep2.txt", "ORIGINAL")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/keep2.txt",
                   expected_state="present")
    mgr = SnapshotManager(sandbox_root)
    snap = mgr.create("tx-2", req, resolved_target=path)
    backed = os.path.join(snap.dir, "target.bin")
    assert read_text(backed) == "ORIGINAL"


def test_snapshot_restore_file(sandbox_root, mkfile, make_req):
    path = mkfile("data/restore.txt", "BEFORE")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/restore.txt",
                   expected_state="present")
    mgr = SnapshotManager(sandbox_root)
    snap = mgr.create("tx-3", req, resolved_target=path)
    # mutate
    write_text(path, "AFTER-MUTATION")
    mgr.restore(snap, resolved_target=path)
    assert read_text(path) == "BEFORE"


def test_snapshot_restore_permissions(sandbox_root, mkfile, make_req):
    path = mkfile("data/perms.txt", "x")
    os.chmod(path, 0o600)
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/perms.txt",
                   expected_state="present")
    mgr = SnapshotManager(sandbox_root)
    snap = mgr.create("tx-4", req, resolved_target=path)
    os.chmod(path, 0o777)
    mgr.restore(snap, resolved_target=path)
    assert (os.stat(path).st_mode & 0o777) == 0o600


def test_snapshot_restore_absent_target(sandbox_root, make_req):
    # snapshot captured with the target ABSENT → restore means DELETE
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/gone.txt",
                   expected_state="absent")
    path = os.path.join(sandbox_root.root, "data", "gone.txt")
    mgr = SnapshotManager(sandbox_root)
    snap = mgr.create("tx-5", req, resolved_target=path)
    assert snap.manifest.get("absent") is True
    # target appears after the snapshot (e.g. partial mutation)
    write_text(path, "unexpected")
    mgr.restore(snap, resolved_target=path)
    assert not os.path.exists(path)


def test_snapshot_failure_blocks_mutation(sandbox_root, make_req):
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/new.txt",
                   expected_state="absent")
    mgr = SnapshotManager(sandbox_root)
    # simulate backup failure: .snapshots dir becomes a file
    snaps_dir = os.path.join(sandbox_root.root, ".snapshots")
    import shutil
    shutil.rmtree(snaps_dir, ignore_errors=True)
    write_text(snaps_dir, "not a dir")
    with pytest.raises(BackupFailed):
        mgr.create("tx-6", req, resolved_target=os.path.join(sandbox_root.root, "data/new.txt"))


def test_snapshot_sha256sums_verify(sandbox_root, mkfile, make_req):
    path = mkfile("data/checksum.txt", "payload-123")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/checksum.txt",
                   expected_state="present")
    mgr = SnapshotManager(sandbox_root)
    snap = mgr.create("tx-7", req, resolved_target=path)
    assert mgr.verify(snap) is True


def test_snapshot_isolation_per_transaction(sandbox_root, mkfile, make_req):
    p1 = mkfile("data/i1.txt", "one")
    p2 = mkfile("data/i2.txt", "two")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/i1.txt",
                   expected_state="present")
    mgr = SnapshotManager(sandbox_root)
    s1 = mgr.create("tx-a", req, resolved_target=p1)
    s2 = mgr.create("tx-b", req, resolved_target=p2)
    assert s1.dir != s2.dir
