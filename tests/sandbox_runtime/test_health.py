"""Health gate — post-verification sandbox health (Sprint 1.3.5 §20)."""

from __future__ import annotations

import os

import pytest

from tests.sandbox_runtime.conftest import make_request, write_text
from agent.sandbox_runtime.health import (
    SandboxHealth,
    check_sandbox_health,
)


def test_health_ok_on_clean_sandbox(sandbox_root):
    report = check_sandbox_health(sandbox_root)
    assert report.ok


def test_health_detects_missing_root(tmp_path):
    health = SandboxHealth(str(tmp_path / "nope"))
    report = health.check()
    assert not report.ok


def test_health_detects_unwritable_root(sandbox_root, monkeypatch):
    def _no_write(*a, **k):
        raise PermissionError("read-only")

    monkeypatch.setattr(os, "access", lambda p, m: False)
    report = check_sandbox_health(sandbox_root)
    assert not report.ok


def test_health_detects_orphan_transactions(sandbox_root, make_req):
    store_dir = os.path.join(sandbox_root.root, ".txn")
    os.makedirs(store_dir, exist_ok=True)
    write_text(os.path.join(store_dir, "orphan-tx.json"), "{}")
    report = check_sandbox_health(sandbox_root)
    assert not report.ok
    assert any("orphan" in name.lower() for name, ok in report.checks if not ok)


def test_health_detects_leaked_processes(sandbox_root):
    # a non-sandbox-owned pid file in the service dir counts as a leak
    svc_dir = os.path.join(sandbox_root.root, ".service")
    os.makedirs(svc_dir, exist_ok=True)
    write_text(os.path.join(svc_dir, "state.json"),
               '{"pid": 999999, "owned": false}')
    report = check_sandbox_health(sandbox_root)
    assert not report.ok


def test_health_detects_lock_leak(sandbox_root):
    locks = os.path.join(sandbox_root.root, ".locks")
    os.makedirs(locks, exist_ok=True)
    write_text(os.path.join(locks, "leaked.lock"), "x")
    report = check_sandbox_health(sandbox_root)
    assert not report.ok


def test_health_checks_manifest_consistency(sandbox_root, mkfile, make_req):
    from agent.sandbox_runtime.snapshot import SnapshotManager
    path = mkfile("data/h1.txt", "x")
    req = make_req(target="data/h1.txt")
    SnapshotManager(sandbox_root).create("tx-h1", req, resolved_target=path)
    report = check_sandbox_health(sandbox_root)
    assert report.ok  # valid snapshots are not a health failure


def test_health_report_lists_checks(sandbox_root):
    report = check_sandbox_health(sandbox_root)
    assert len(report.checks) >= 5
