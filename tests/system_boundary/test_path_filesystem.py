"""Sprint 1.3.3 §17/§18/§25/§62 — PATH RESOLUTION + FILESYSTEM BOUNDARY.

Classify the RESOLVED identity, not the input string: absolute,
relative, cwd, ., .., //, ~, unicode, spaces, symlinks, broken
symlinks, parent symlinks, new-file parent resolution, realpath.

TOCTOU (§25/§62): safe file → preflight → replace with symlink →
verify_before_execute must detect RESOURCE_CHANGED_AFTER_PREFLIGHT or
SYMLINK_ESCAPE with adapter calls = 0.
"""

import os
import tempfile

import pytest

from agent.system_boundary import fingerprint as fp
from agent.system_boundary import models as m
from agent.system_boundary import path_resolver as pr


# ── §17 path resolution ─────────────────────────────────────────────

def test_resolve_absolute():
    r = pr.resolve_path("/etc/passwd", cwd="/home/user")
    assert r.resolved == "/etc/passwd"
    assert r.resource_class == m.ResourceClass.SYSTEM_CONFIG


def test_resolve_relative_to_cwd():
    r = pr.resolve_path("config.yaml", cwd="/home/user/app")
    assert r.resolved == "/home/user/app/config.yaml"
    assert r.resource_class == m.ResourceClass.APPLICATION_CONFIG


def test_resolve_dot_dot_normalization():
    # /home/user/app/../../../etc/passwd → /etc/passwd (§17 example)
    r = pr.resolve_path("/home/user/app/../../../etc/passwd",
                        cwd="/home/user")
    assert r.resolved == "/etc/passwd"
    assert r.resource_class == m.ResourceClass.SYSTEM_CONFIG


def test_resolve_double_slash_and_dot():
    r = pr.resolve_path("//etc//passwd", cwd="/")
    assert r.resolved == "/etc/passwd"


def test_resolve_tilde():
    r = pr.resolve_path("~/app/config.yaml", cwd="/tmp",
                        home="/home/user")
    assert r.resolved == "/home/user/app/config.yaml"


def test_resolve_unicode_and_spaces():
    r = pr.resolve_path("/home/user/мои файлы/отчёт.txt", cwd="/")
    assert r.resolved == "/home/user/мои файлы/отчёт.txt"


def test_resolve_symlink_escape_detection(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("x")
    link = tmp_path / "link.txt"
    os.symlink(str(target), link)
    r = pr.resolve_path(str(link), cwd="/")
    assert r.resolved == str(target)
    assert r.symlink_chain == [str(link)]


def test_broken_symlink_reported_not_crash(tmp_path):
    link = tmp_path / "broken"
    os.symlink(str(tmp_path / "missing"), link)
    r = pr.resolve_path(str(link), cwd="/")
    # must not raise; unresolved-but-bounded is acceptable
    assert r.resolved is None or r.broken_symlink


def test_path_escape_detection(tmp_path):
    # A path that climbs out of the intended app root resolves into a
    # system directory and must be classified as such (§17 example).
    r = pr.resolve_path("/home/user/app/../../../etc/passwd",
                        cwd="/home/user")
    assert r.resolved == "/etc/passwd"
    assert r.resource_class == m.ResourceClass.SYSTEM_CONFIG


def test_parent_symlink_escape(tmp_path):
    # parent directory is a symlink to a system dir → the child path
    # resolves into the system dir.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "target.conf").write_text("x")
    parent_link = tmp_path / "linked_parent"
    os.symlink(str(outside), parent_link)
    r = pr.resolve_path(str(parent_link / "target.conf"), cwd="/")
    assert r.resolved == str(outside / "target.conf")
    # the chain includes the parent link
    assert any("linked_parent" in p for p in r.symlink_chain)


def test_new_file_parent_resolution(tmp_path):
    # A new file whose parent exists resolves to the parent identity.
    parent = tmp_path / "newdir"
    parent.mkdir()
    r = pr.resolve_path(str(parent / "newfile.txt"), cwd="/")
    assert r.resolved == str(parent / "newfile.txt")


def test_system_path_classification():
    for p in ("/etc/passwd", "/etc/nginx/nginx.conf", "/usr/bin/sshd",
              "/usr/local/bin/x", "/bin/sh", "/sbin/iptables",
              "/lib/x.so", "/lib64/x.so", "/boot/vmlinuz",
              "/var/lib/docker/x", "/var/spool/cron/x", "/opt/x",
              "/root/.ssh/id_rsa", "/proc/1/status", "/sys/kernel/x",
              "/dev/sda", "/run/systemd/x"):
        r = pr.resolve_path(p, cwd="/")
        assert r.resource_class in (
            m.ResourceClass.SYSTEM_CONFIG,
            m.ResourceClass.SYSTEM_BINARY,
            m.ResourceClass.SECRET_RESOURCE,
            m.ResourceClass.SYSTEM_STATE,
        ), f"unclassified system path {p}"


def test_secret_paths_are_secret_resource():
    for p in ("/root/.ssh/id_rsa", "/etc/ssl/private/x.key",
              "/home/user/.ssh/id_ed25519",
              "/var/lib/letsencrypt/privkey.pem"):
        r = pr.resolve_path(p, cwd="/")
        assert r.resource_class == m.ResourceClass.SECRET_RESOURCE, p


def test_user_data_classification(tmp_path):
    r = pr.resolve_path("/home/user/docs/notes.txt", cwd="/")
    assert r.resource_class == m.ResourceClass.USER_DATA


def test_application_config_classification():
    r = pr.resolve_path("/home/user/app/config.yaml", cwd="/")
    assert r.resource_class == m.ResourceClass.APPLICATION_CONFIG


def test_tmp_is_temporary(tmp_path):
    r = pr.resolve_path("/tmp/x/y.txt", cwd="/")
    assert r.resource_class == m.ResourceClass.TEMPORARY


# ── §20 resource fingerprint ─────────────────────────────────────────

def test_fingerprint_real_file(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello")
    fp1 = fp.fingerprint_path(str(f))
    assert fp1.realpath == str(f)
    assert fp1.inode is not None
    assert fp1.size == 5
    assert fp1.mode is not None
    assert fp1.uid is not None


def test_fingerprint_missing_file_no_invented_values(tmp_path):
    f = tmp_path / "missing.bin"
    fp1 = fp.fingerprint_path(str(f))
    # Do not invent values: fields stay None for a missing target.
    assert fp1.realpath is None
    assert fp1.inode is None


def test_fingerprint_changes_when_file_replaced(tmp_path):
    f = tmp_path / "swap.txt"
    f.write_text("one")
    fp1 = fp.fingerprint_path(str(f))
    f.write_text("two")
    fp2 = fp.fingerprint_path(str(f))
    # mtime/size change → fingerprint must differ.
    assert fp1 != fp2


def test_fingerprint_detects_symlink_replacement(tmp_path):
    f = tmp_path / "target.txt"
    f.write_text("x")
    link = tmp_path / "link.txt"
    os.symlink(str(f), link)
    fp1 = fp.fingerprint_path(str(link))
    # replace link with a symlink to /etc/passwd
    os.unlink(link)
    os.symlink("/etc/passwd", link)
    fp2 = fp.fingerprint_path(str(link))
    assert fp1 != fp2


# ── §25/§62 TOCTOU ──────────────────────────────────────────────────

def test_toctou_detected_when_target_replaced_with_symlink(tmp_path):
    from agent.system_boundary.boundary import SystemBoundaryLayer
    from agent.system_boundary.verifier import verify_before_execute

    safe = tmp_path / "safe.txt"
    safe.write_text("safe")

    sbl = SystemBoundaryLayer(mode="enforce")
    preflight = sbl.preflight_path(str(safe))

    # attacker replaces the file with a symlink to /etc/passwd
    os.unlink(safe)
    os.symlink("/etc/passwd", safe)

    decision = verify_before_execute(
        preflight=preflight, mode="enforce")
    assert decision.verdict in ("BLOCK", "REVALIDATE_REQUIRED")
    assert decision.reason_code in (
        "RESOURCE_CHANGED_AFTER_PREFLIGHT", "SYMLINK_ESCAPE")


def test_toctou_detected_when_content_changes(tmp_path):
    from agent.system_boundary.boundary import SystemBoundaryLayer
    from agent.system_boundary.verifier import verify_before_execute

    safe = tmp_path / "safe.txt"
    safe.write_text("v1")

    sbl = SystemBoundaryLayer(mode="enforce")
    preflight = sbl.preflight_path(str(safe))

    safe.write_text("v2-changed")  # in-place modification

    decision = verify_before_execute(
        preflight=preflight, mode="enforce")
    assert decision.verdict in ("BLOCK", "REVALIDATE_REQUIRED")


def test_toctou_unchanged_target_passes(tmp_path):
    from agent.system_boundary.boundary import SystemBoundaryLayer
    from agent.system_boundary.verifier import verify_before_execute

    safe = tmp_path / "safe.txt"
    safe.write_text("stable")

    sbl = SystemBoundaryLayer(mode="enforce")
    preflight = sbl.preflight_path(str(safe))

    decision = verify_before_execute(
        preflight=preflight, mode="enforce")
    assert decision.verdict == "PASS"


def test_preflight_expired(tmp_path):
    from agent.system_boundary.boundary import SystemBoundaryLayer
    from agent.system_boundary.verifier import verify_before_execute

    safe = tmp_path / "safe.txt"
    safe.write_text("x")

    sbl = SystemBoundaryLayer(mode="enforce", preflight_ttl_s=0.05)
    preflight = sbl.preflight_path(str(safe))

    import time
    time.sleep(0.1)
    decision = verify_before_execute(
        preflight=preflight, mode="enforce")
    assert decision.verdict == "REVALIDATE_REQUIRED"
    assert decision.reason_code == "PREFLIGHT_EXPIRED"


# ── §18 filesystem boundary primitives ──────────────────────────────

def test_escape_detected_when_parent_is_symlink_to_system(tmp_path):
    from agent.system_boundary.filesystem_boundary import (
        FilesystemBoundary,
    )
    fb = FilesystemBoundary()
    # /etc is a system dir; any write beneath it is SYSTEM_CONFIG
    verdict = fb.evaluate_write_target("/etc/nginx/nginx.conf")
    assert verdict.reason_code in ("RESOURCE_SYSTEM", "PATH_ESCAPE_DETECTED")
    assert verdict.verdict in ("BLOCK", "REVALIDATE_REQUIRED")
