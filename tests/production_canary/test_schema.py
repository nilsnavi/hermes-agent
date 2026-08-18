"""Sprint 1.3.7 §5 — strict schema + content-size control."""
from __future__ import annotations

import json

import pytest

from agent.production_canary.core import MAX_CANARY_SIZE
from agent.production_canary.schema import (
    make_canary,
    validate_canary_dict,
    validate_content_bytes,
)


def test_valid_canary():
    d = make_canary(gen=1, canary_id="c1", baseline_sha="abc123",
                    updated_at="2026-08-18T00:00:00Z")
    assert validate_canary_dict(d) == []


def test_arbitrary_key_rejected():
    d = make_canary(1, "c1", "abc", "t")
    d["evil"] = "x"
    assert "unexpected keys" in " ".join(validate_canary_dict(d))


def test_wrong_schema_version():
    d = make_canary(1, "c1", "abc", "t")
    d["schema_version"] = 999
    assert any("schema_version" in e for e in validate_canary_dict(d))


def test_generation_not_int():
    d = make_canary(1, "c1", "abc", "t")
    d["generation"] = "two"
    assert any("generation must be an int" in e for e in validate_canary_dict(d))


@pytest.mark.parametrize("bad", [
    {"schema_version": 1, "canary_id": "c", "cmd": "rm -rf /"},
    {"schema_version": 1, "canary_id": "c", "generation": 1,
     "updated_at": "t", "updated_by": "x", "baseline_sha": "sha",
     "path": "/etc/shadow"},
    {"schema_version": 1, "canary_id": "c", "token": "ghp_abcdefghijklmnop"},
    {"schema_version": 1, "canary_id": "c", "env": "HERMES_X=1"},
])
def test_forbidden_content_rejected(bad):
    errs = validate_canary_dict(bad)
    assert errs  # must have at least one violation (unknown key / marker)


def test_not_a_dict():
    assert validate_canary_dict(["list"]) != []
    assert validate_canary_dict("string") != []
    assert validate_canary_dict(42) != []


def test_size_bound():
    big = b"{ \"pad\": \"" + b"x" * (MAX_CANARY_SIZE + 1) + b"\" }"
    assert any("size exceeds" in e for e in validate_content_bytes(big))


def test_non_utf8():
    assert any("UTF-8" in e for e in validate_content_bytes(b"\xff\xfe\x00\x01bad"))


def test_non_json():
    assert any("JSON" in e for e in validate_content_bytes(b"not json at all"))


def test_valid_bytes_roundtrip():
    d = make_canary(1, "c1", "abc", "t")
    raw = json.dumps(d).encode()
    assert validate_content_bytes(raw) == []


def test_updated_by_must_be_canary_marker():
    d = make_canary(1, "c1", "abc", "t")
    d["updated_by"] = "someone-else"
    assert any("updated_by" in e for e in validate_canary_dict(d))
