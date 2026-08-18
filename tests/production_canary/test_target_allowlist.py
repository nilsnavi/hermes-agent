"""Sprint 1.3.7 §4/§6/§23 — exact single-target allowlist + deny matrix."""
from __future__ import annotations

import os

import pytest

from agent.production_canary.target_allowlist import TargetAllowlist, TargetResolution


@pytest.fixture
def al(tmp_path):
    # canonical canary path inside a temp tree (mode 700 parent)
    parent = tmp_path / "managed" / "canary"
    parent.mkdir(parents=True, exist_ok=True)
    os.chmod(parent, 0o700)
    target = str(parent / "runtime-canary.json")
    return TargetAllowlist(canonical=target)


def test_exact_target_allowed(al):
    res = al.resolve(al.canonical)
    assert res.allowed is True
    assert res.reason == "ok"


def test_prefix_only_not_allowed(al):
    # a sibling/prefix path must NOT match (no prefix-only checks)
    sibling = os.path.join(os.path.dirname(al.canonical), "runtime-canary-evil.json")
    assert al.resolve(sibling).allowed is False
    parent = os.path.dirname(al.canonical)
    assert al.resolve(parent).allowed is False


def test_glob_like_denied(al):
    assert al.resolve(os.path.join(os.path.dirname(al.canonical), "*.json")).allowed is False


def test_env_hint_mismatch_denied(al):
    # env hint never widens trust to a different path
    other = os.path.join(os.path.dirname(al.canonical), "other.json")
    assert al.resolve(al.canonical, env_hint=other).allowed is False


def test_empty_env_hint_ok(al):
    assert al.resolve(al.canonical, env_hint=None).allowed is True


@pytest.mark.parametrize("bad", [
    "~/.hermes/config.yaml",
    "~/.hermes/state.db",
    "~/.hermes/.env",
    "~/.ssh/authorized_keys",
    "/etc/passwd",
    "/run/systemd",
    "~/.hermes/cron/jobs.json",
])
def test_hard_deny_matrix(al, bad):
    # these must be denied even if they were (incorrectly) passed as the canonical
    probe = TargetAllowlist(canonical=os.path.abspath(os.path.expanduser(bad)))
    assert probe.resolve(probe.canonical).allowed is False


def test_symlink_target_denied(al, tmp_path):
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "managed" / "canary" / "runtime-canary.json"
    if link.exists():
        link.unlink()
    link.symlink_to(real)
    res = al.resolve(al.canonical)
    assert res.allowed is False
    assert "symlink" in res.reason


def test_symlink_parent_denied(al, tmp_path):
    # make parent a symlink: replace canary dir with a symlink to elsewhere
    parent = tmp_path / "managed" / "canary"
    real_parent = tmp_path / "elsewhere"
    real_parent.mkdir()
    parent.rename(real_parent / "real_canary_dir")
    parent.symlink_to(real_parent / "real_canary_dir", target_is_directory=True)
    res = al.resolve(al.canonical)
    assert res.allowed is False
    assert "symlink" in res.reason
