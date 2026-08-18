"""Sprint 1.3.7 §7/§9 — production canary feature flags (Phase A: off)."""
from __future__ import annotations

import pytest

from agent.production_canary.flags import (
    get_flag_enabled,
    get_mode,
    Mode,
    canary_enabled,
)


def test_default_enabled_false(monkeypatch):
    monkeypatch.delenv("HERMES_PRODUCTION_CANARY_V2_ENABLED", raising=False)
    monkeypatch.delenv("HERMES_PRODUCTION_CANARY_V2_MODE", raising=False)
    assert get_flag_enabled() is False


def test_default_mode_off(monkeypatch):
    monkeypatch.delenv("HERMES_PRODUCTION_CANARY_V2_ENABLED", raising=False)
    monkeypatch.delenv("HERMES_PRODUCTION_CANARY_V2_MODE", raising=False)
    assert get_mode() is Mode.OFF


def test_unknown_mode_is_off(monkeypatch):
    monkeypatch.setenv("HERMES_PRODUCTION_CANARY_V2_MODE", "garbage")
    assert get_mode() is Mode.OFF


def test_explicit_off(monkeypatch):
    monkeypatch.setenv("HERMES_PRODUCTION_CANARY_V2_MODE", "off")
    assert get_mode() is Mode.OFF


def test_shadow_mode(monkeypatch):
    monkeypatch.setenv("HERMES_PRODUCTION_CANARY_V2_MODE", "shadow")
    assert get_mode() is Mode.SHADOW


def test_canary_mode(monkeypatch):
    monkeypatch.setenv("HERMES_PRODUCTION_CANARY_V2_MODE", "canary")
    assert get_mode() is Mode.CANARY


def test_case_insensitive_modes(monkeypatch):
    for v, expected in (("ShAdOw", Mode.SHADOW), ("CANARY", Mode.CANARY), ("OFF", Mode.OFF)):
        monkeypatch.setenv("HERMES_PRODUCTION_CANARY_V2_MODE", v)
        assert get_mode() is expected


def test_enabled_flag_parsing(monkeypatch):
    for v, expected in (("true", True), ("1", True), ("yes", True),
                        ("false", False), ("0", False), ("", False), ("junk", False)):
        monkeypatch.setenv("HERMES_PRODUCTION_CANARY_V2_ENABLED", v)
        assert get_flag_enabled() is expected


def test_canary_enabled_requires_both(monkeypatch):
    # canary_enabled() = enabled True AND mode == CANARY
    monkeypatch.setenv("HERMES_PRODUCTION_CANARY_V2_ENABLED", "false")
    monkeypatch.setenv("HERMES_PRODUCTION_CANARY_V2_MODE", "canary")
    assert canary_enabled() is False
    monkeypatch.setenv("HERMES_PRODUCTION_CANARY_V2_ENABLED", "true")
    assert canary_enabled() is True
    monkeypatch.setenv("HERMES_PRODUCTION_CANARY_V2_MODE", "shadow")
    assert canary_enabled() is False
