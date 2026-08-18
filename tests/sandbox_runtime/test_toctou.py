"""TOCTOU matrix — resource changes between preflight and execution (Sprint 1.3.5 §26)."""

from __future__ import annotations

import os

import pytest

from tests.sandbox_runtime.conftest import make_request, write_text
from agent.sandbox_runtime.exceptions import ResourceChangedAfterPreflight
from agent.sandbox_runtime.models import SandboxOperation
from agent.sandbox_runtime.preflight import compute_fingerprint
from agent.sandbox_runtime.toctou import verify_toctou


def test_t1_file_changed_after_preflight(sandbox_root, mkfile, make_req):
    path = mkfile("data/t1.txt", "v1")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/t1.txt",
                   expected_state="present")
    fp = compute_fingerprint(req, sandbox_root)
    write_text(path, "v2")
    with pytest.raises(ResourceChangedAfterPreflight):
        verify_toctou(req, sandbox_root, fp)


def test_t2_inode_changed(sandbox_root, mkfile, make_req):
    path = mkfile("data/t2.txt", "x")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/t2.txt",
                   expected_state="present")
    fp = compute_fingerprint(req, sandbox_root)
    # replace the file (new inode) with identical content
    os.remove(path)
    write_text(path, "x")
    with pytest.raises(ResourceChangedAfterPreflight):
        verify_toctou(req, sandbox_root, fp)


def test_t3_symlink_swapped(sandbox_root, make_req):
    target = os.path.join(sandbox_root.root, "data", "t3.txt")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    write_text(target, "real")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/t3.txt",
                   expected_state="present")
    fp = compute_fingerprint(req, sandbox_root)
    os.remove(target)
    os.symlink("/etc/passwd", target)
    # the symlink swap now RESOLVES OUTSIDE the sandbox → blocked at
    # the path boundary (SandboxPathEscape) OR flagged as TOCTOU —
    # either way adapter calls = 0
    from agent.sandbox_runtime.exceptions import SandboxPathEscape
    with pytest.raises((ResourceChangedAfterPreflight, SandboxPathEscape)):
        verify_toctou(req, sandbox_root, fp)


def test_t4_parent_symlink_swapped(sandbox_root, make_req):
    data = os.path.join(sandbox_root.root, "data")
    os.makedirs(data, exist_ok=True)
    write_text(os.path.join(data, "t4.txt"), "x")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/t4.txt",
                   expected_state="present")
    fp = compute_fingerprint(req, sandbox_root)
    os.rename(data, data + "_old")
    os.symlink("/etc", data)
    # parent swap makes the resolved target escape the sandbox → blocked
    # at the path boundary (SandboxPathEscape) OR flagged as TOCTOU
    from agent.sandbox_runtime.exceptions import SandboxPathEscape
    with pytest.raises((ResourceChangedAfterPreflight, SandboxPathEscape)):
        verify_toctou(req, sandbox_root, fp)


def test_t5_permissions_changed(sandbox_root, mkfile, make_req):
    path = mkfile("data/t5.txt", "x")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/t5.txt",
                   expected_state="present")
    fp = compute_fingerprint(req, sandbox_root)
    os.chmod(path, 0o600)
    with pytest.raises(ResourceChangedAfterPreflight):
        verify_toctou(req, sandbox_root, fp)


def test_t8_target_deleted(sandbox_root, mkfile, make_req):
    path = mkfile("data/t8.txt", "x")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/t8.txt",
                   expected_state="present")
    fp = compute_fingerprint(req, sandbox_root)
    os.remove(path)
    with pytest.raises(ResourceChangedAfterPreflight):
        verify_toctou(req, sandbox_root, fp)


def test_t9_target_created_unexpectedly(sandbox_root, make_req):
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/t9.txt",
                   expected_state="absent")
    fp = compute_fingerprint(req, sandbox_root)
    write_text(os.path.join(sandbox_root.root, "data", "t9.txt"), "sneaky")
    with pytest.raises(ResourceChangedAfterPreflight):
        verify_toctou(req, sandbox_root, fp)


def test_unchanged_state_passes(sandbox_root, mkfile, make_req):
    path = mkfile("data/ok.txt", "stable")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/ok.txt",
                   expected_state="present")
    fp = compute_fingerprint(req, sandbox_root)
    verify_toctou(req, sandbox_root, fp)  # must not raise
    assert os.path.exists(path)
