"""Sandbox path boundary — escape, symlink, TOCTOU path validation (Sprint 1.3.5 §4/§27)."""

from __future__ import annotations

import os

import pytest

from agent.sandbox_runtime.exceptions import SandboxPathEscape
from agent.sandbox_runtime.root import resolve_sandbox_path

ESCAPES = [
    "../../etc/passwd",
    "/etc/passwd",
    "/proc/self/environ",
    "/sys/kernel",
    "/dev/null",
    "/run/systemd",
    "/boot",
    "/root/.bashrc",
    "/home/hermes/.ssh/id_rsa",
    "/home/hermes/.hermes/config.yaml",
    "/home/hermes/.hermes/state.db",
    "/etc/systemd/system/hermes-gateway.service",
]


@pytest.mark.parametrize("target", ESCAPES)
def test_absolute_and_dotdot_escapes_denied(sandbox_root, target):
    with pytest.raises(SandboxPathEscape):
        resolve_sandbox_path(sandbox_root.root, target)


def test_relative_path_inside_ok(sandbox_root):
    p = resolve_sandbox_path(sandbox_root.root, "data/hello.txt")
    assert p.startswith(sandbox_root.root)
    assert p == os.path.join(sandbox_root.root, "data", "hello.txt")


def test_symlink_escape_denied(sandbox_root):
    link = os.path.join(sandbox_root.root, "link")
    os.symlink("/etc", link)
    with pytest.raises(SandboxPathEscape):
        resolve_sandbox_path(sandbox_root.root, "link/passwd")


def test_parent_symlink_escape_denied(sandbox_root):
    sub = os.path.join(sandbox_root.root, "sub")
    os.makedirs(sub)
    os.symlink("/home/hermes/.hermes", os.path.join(sub, "escape"))
    with pytest.raises(SandboxPathEscape):
        resolve_sandbox_path(sandbox_root.root, "sub/escape/config.yaml")


def test_sandbox_root_must_be_absolute(tmp_path):
    with pytest.raises(SandboxPathEscape):
        resolve_sandbox_path("relative/root", "x.txt")


def test_target_must_not_be_absolute_outside():
    with pytest.raises(SandboxPathEscape):
        resolve_sandbox_path("/tmp/box", "/tmp/box/../box2/x")


def test_lexical_normalization(sandbox_root):
    p = resolve_sandbox_path(sandbox_root.root, "a/./b/../c.txt")
    assert p == os.path.join(sandbox_root.root, "a", "c.txt")


def test_null_bytes_rejected(sandbox_root):
    with pytest.raises(SandboxPathEscape):
        resolve_sandbox_path(sandbox_root.root, "data\x00/x")


def test_production_hermes_paths_denied(tmp_path):
    root = str(tmp_path / "sandbox")
    os.makedirs(root)
    with pytest.raises(SandboxPathEscape):
        resolve_sandbox_path(root, "/home/hermes/.hermes/sandbox/system-mutation/../../config.yaml")


def test_missing_parent_denied(sandbox_root):
    # parent must resolve inside sandbox; a target under a non-existent
    # dir is still allowed for CREATE (parent checked separately by preflight)
    p = resolve_sandbox_path(sandbox_root.root, "no/such/dir/f.txt")
    assert p.startswith(sandbox_root.root)
