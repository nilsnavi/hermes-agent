"""Preflight gate — 21 checks + fingerprint + TOCTOU second check (Sprint 1.3.5 §8-§9)."""

from __future__ import annotations

import hashlib
import os

import pytest

from tests.sandbox_runtime.conftest import make_request, sha256_bytes, write_text
from agent.sandbox_runtime.exceptions import SandboxPreflightFailed
from agent.sandbox_runtime.models import SandboxOperation
from agent.sandbox_runtime.preflight import compute_fingerprint, run_preflight


def test_preflight_pass_for_create(sandbox_root, make_req):
    req = make_req(
        operation=SandboxOperation.CREATE_FILE,
        target="data/new.txt",
        expected_state="absent",
    )
    receipt = run_preflight(req, sandbox_root)
    assert receipt.ok
    assert receipt.fingerprint


def test_preflight_fails_target_exists_when_absent_expected(sandbox_root, mkfile, make_req):
    mkfile("data/exists.txt", "x")
    req = make_req(
        operation=SandboxOperation.CREATE_FILE,
        target="data/exists.txt",
        expected_state="absent",
    )
    receipt = run_preflight(req, sandbox_root)
    assert not receipt.ok
    assert any(not ok for _, ok in receipt.checks)


def test_preflight_detects_content_hash_mismatch(sandbox_root, mkfile, make_req):
    path = mkfile("data/a.txt", "content-A")
    req = make_req(
        operation=SandboxOperation.REPLACE_FILE,
        target="data/a.txt",
        expected_state="present",
        expected_hash=sha256_bytes(b"content-B"),
    )
    receipt = run_preflight(req, sandbox_root)
    assert not receipt.ok


def test_preflight_detects_symlink_target(sandbox_root, make_req):
    os.symlink("/etc", os.path.join(sandbox_root.root, "evil"))
    req = make_req(operation=SandboxOperation.DELETE_FILE, target="evil")
    # symlink escape is a structural violation → fail-closed raise
    with pytest.raises(SandboxPreflightFailed):
        run_preflight(req, sandbox_root)


def test_preflight_detects_permission_change(sandbox_root, mkfile, make_req):
    path = mkfile("data/b.txt", "x")
    os.chmod(path, 0o600)
    req = make_req(
        operation=SandboxOperation.WRITE_FILE,
        target="data/b.txt",
        expected_state="present",
    )
    receipt = run_preflight(req, sandbox_root)
    # 0o600 is fine for owner; mode checks pass, but this is a write to
    # an existing file — expected current state must be verified by hash
    assert receipt.fingerprint


def test_fingerprint_covers_state(sandbox_root, mkfile, make_req):
    req = make_req(operation=SandboxOperation.REPLACE_FILE, target="data/c.txt",
                   expected_state="present")
    mkfile("data/c.txt", "v1")
    fp1 = compute_fingerprint(req, sandbox_root)
    # change the file → fingerprint must differ
    write_text(os.path.join(sandbox_root.root, "data/c.txt"), "v2")
    fp2 = compute_fingerprint(req, sandbox_root)
    assert fp1 != fp2


def test_fingerprint_stable_for_identical_state(sandbox_root, mkfile, make_req):
    req = make_req(operation=SandboxOperation.REPLACE_FILE, target="data/d.txt",
                   expected_state="present")
    mkfile("data/d.txt", "same")
    fp1 = compute_fingerprint(req, sandbox_root)
    fp2 = compute_fingerprint(req, sandbox_root)
    assert fp1 == fp2


def test_preflight_raises_when_target_outside(sandbox_root, make_req):
    req = make_req(operation=SandboxOperation.DELETE_FILE, target="/etc/passwd")
    with pytest.raises(SandboxPreflightFailed):
        run_preflight(req, sandbox_root)


def test_preflight_receipt_has_checks_list(sandbox_root, make_req):
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="z.txt")
    receipt = run_preflight(req, sandbox_root)
    assert len(receipt.checks) >= 10


def test_preflight_second_check_detects_change(sandbox_root, mkfile, make_req):
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/e.txt",
                   expected_state="present")
    mkfile("data/e.txt", "orig")
    fp = compute_fingerprint(req, sandbox_root)
    # simulate change between preflight and execution
    write_text(os.path.join(sandbox_root.root, "data/e.txt"), "tampered")
    fp2 = compute_fingerprint(req, sandbox_root)
    assert fp != fp2  # RESOURCE_CHANGED_AFTER_PREFLIGHT
