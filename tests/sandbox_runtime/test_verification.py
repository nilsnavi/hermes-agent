"""Independent post-execution verification — adapter result is NOT proof (Sprint 1.3.5 §19)."""

from __future__ import annotations

import os

import pytest

from tests.sandbox_runtime.conftest import make_request, sha256_bytes, write_text
from agent.sandbox_runtime.exceptions import VerifyFailed
from agent.sandbox_runtime.models import SandboxOperation
from agent.sandbox_runtime.verifier import verify_mutation


def test_verify_file_created(sandbox_root, mkfile, make_req):
    path = mkfile("data/v1.txt", "content")
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/v1.txt",
                   expected_state="present",
                   expected_hash=sha256_bytes(b"content"))
    verify_mutation(req, sandbox_root, adapter_said_success=True)


def test_verify_reports_content_mismatch(sandbox_root, mkfile, make_req):
    path = mkfile("data/v2.txt", "wrong-content")
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/v2.txt",
                   expected_state="present",
                   expected_hash=sha256_bytes(b"expected"))
    with pytest.raises(VerifyFailed):
        verify_mutation(req, sandbox_root, adapter_said_success=True)


def test_verify_file_absent_after_delete(sandbox_root, mkfile, make_req):
    mkfile("data/v3.txt", "x")
    req = make_req(operation=SandboxOperation.DELETE_FILE, target="data/v3.txt",
                   expected_state="absent")
    os.remove(os.path.join(sandbox_root.root, "data", "v3.txt"))
    verify_mutation(req, sandbox_root, adapter_said_success=True)


def test_verify_delete_failed_when_file_remains(sandbox_root, mkfile, make_req):
    mkfile("data/v4.txt", "x")
    req = make_req(operation=SandboxOperation.DELETE_FILE, target="data/v4.txt",
                   expected_state="absent")
    with pytest.raises(VerifyFailed):
        verify_mutation(req, sandbox_root, adapter_said_success=True)


def test_verify_chmod_exact(sandbox_root, mkfile, make_req):
    path = mkfile("data/v5.txt", "x")
    os.chmod(path, 0o640)
    req = make_req(operation=SandboxOperation.CHMOD, target="data/v5.txt",
                   expected_state="present", arguments={"mode": 0o640})
    verify_mutation(req, sandbox_root, adapter_said_success=True)


def test_verify_chmod_mismatch(sandbox_root, mkfile, make_req):
    path = mkfile("data/v6.txt", "x")
    req = make_req(operation=SandboxOperation.CHMOD, target="data/v6.txt",
                   expected_state="present", arguments={"mode": 0o600})
    os.chmod(path, 0o777)
    with pytest.raises(VerifyFailed):
        verify_mutation(req, sandbox_root, adapter_said_success=True)


def test_verify_rename_target(sandbox_root, mkfile, make_req):
    mkfile("data/v7.txt", "x")
    req = make_req(operation=SandboxOperation.RENAME_FILE, target="data/v7.txt",
                   expected_state="absent", arguments={"to": "data/v7-renamed.txt"})
    os.rename(os.path.join(sandbox_root.root, "data", "v7.txt"),
              os.path.join(sandbox_root.root, "data", "v7-renamed.txt"))
    verify_mutation(req, sandbox_root, adapter_said_success=True)


def test_verify_adapter_success_but_state_differs(sandbox_root, mkfile, make_req):
    mkfile("data/v8.txt", "x")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/v8.txt",
                   expected_state="present", expected_hash=sha256_bytes(b"NEW"))
    # adapter claims success but nothing changed on disk
    with pytest.raises(VerifyFailed):
        verify_mutation(req, sandbox_root, adapter_said_success=True)


def test_verify_size_check(sandbox_root, mkfile, make_req):
    path = mkfile("data/v9.txt", "12345")
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/v9.txt",
                   expected_state="present", arguments={"size": 5})
    verify_mutation(req, sandbox_root, adapter_said_success=True)


def test_verify_owner_check(sandbox_root, mkfile, make_req):
    mkfile("data/v10.txt", "x")
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/v10.txt",
                   expected_state="present")
    verify_mutation(req, sandbox_root, adapter_said_success=True)
