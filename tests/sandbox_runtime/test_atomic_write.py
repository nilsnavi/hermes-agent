"""Atomic file write — temp+fsync+rename (Sprint 1.3.5 §15)."""

from __future__ import annotations

import os

import pytest

from tests.sandbox_runtime.conftest import read_text, write_text
from agent.sandbox_runtime.filesystem import atomic_write


def test_atomic_write_creates_file(tmp_path):
    target = os.path.join(str(tmp_path), "a.txt")
    atomic_write(target, b"hello")
    assert read_text(target) == "hello"


def test_atomic_write_no_temp_left_behind(tmp_path):
    target = os.path.join(str(tmp_path), "b.txt")
    atomic_write(target, b"data")
    # only our temp artifacts matter (the repo's root conftest may add
    # its own hermes_test dir to tmp_path)
    leftovers = [f for f in os.listdir(str(tmp_path))
                 if f.startswith(".sandbox-write-")]
    assert leftovers == []


def test_atomic_write_replaces_content(tmp_path):
    target = os.path.join(str(tmp_path), "c.txt")
    write_text(target, "old")
    atomic_write(target, b"new-content")
    assert read_text(target) == "new-content"


def test_atomic_write_preserves_mode(tmp_path):
    target = os.path.join(str(tmp_path), "d.txt")
    atomic_write(target, b"x", mode=0o600)
    assert (os.stat(target).st_mode & 0o777) == 0o600


def test_atomic_write_failure_keeps_original(tmp_path, monkeypatch):
    target = os.path.join(str(tmp_path), "e.txt")
    write_text(target, "ORIGINAL")

    def _boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        atomic_write(target, b"NEW")
    assert read_text(target) == "ORIGINAL"


def test_atomic_write_parent_missing_raises(tmp_path):
    target = os.path.join(str(tmp_path), "no", "such", "f.txt")
    with pytest.raises(OSError):
        atomic_write(target, b"x")


def test_atomic_write_content_exact(tmp_path):
    target = os.path.join(str(tmp_path), "f.txt")
    payload = b"\x00\x01binary\xff" * 100
    atomic_write(target, payload)
    with open(target, "rb") as fh:
        assert fh.read() == payload
