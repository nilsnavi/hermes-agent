"""Sprint 1.3.12 — foundation flags (off/shadow/inspect only)."""
from __future__ import annotations

from agent.service_restart_foundation import flags


class TestFlags:
    def test_default_mode_off(self):
        assert flags.mode({}) == "off"

    def test_unknown_mode_falls_back_off(self):
        assert flags.mode({"HERMES_SERVICE_RESTART_FOUNDATION_V2_MODE": "execute"}) == "off"

    def test_valid_modes(self):
        for m in ("off", "shadow", "inspect"):
            assert flags.mode({"HERMES_SERVICE_RESTART_FOUNDATION_V2_MODE": m}) == m

    def test_canary_and_execute_not_valid(self):
        for m in ("canary", "execute", "enforce"):
            assert flags.mode({"HERMES_SERVICE_RESTART_FOUNDATION_V2_MODE": m}) == "off"

    def test_disabled_by_default(self):
        assert flags.enabled({}) is False

    def test_enabled_true_when_set(self):
        assert flags.enabled({"HERMES_SERVICE_RESTART_FOUNDATION_V2_ENABLED": "true"}) is True

    def test_restart_authority_always_false(self):
        # never granted by flags in 1.3.12
        assert flags.restart_authority({}) is False
        assert flags.restart_authority({"HERMES_SERVICE_RESTART_FOUNDATION_V2_ENABLED": "true"}) is False