"""Sprint 1.3.12 — registry + service-class restriction.

Future restart candidate can ONLY be HERMES_AUXILIARY. Everything else is hard
denied (gateway, scheduler, database, network, security, SSH, docker/auth,
UNKNOWN, ...).
"""
from __future__ import annotations

import pytest

from agent.service_restart_foundation.registry import (
    ALLOWED_CLASS,
    HARD_DENY_CLASSES,
    RestartRegistry,
    class_allowed,
    default_aux_profile,
    default_registry,
)
from agent.service_restart_foundation.models import RestartProfile


def _mk(cls):
    return RestartProfile(
        service_id="svc", profile_version=1,
        unit_name="svc.service", service_class=cls, criticality="LOW",
        restart_supported=True, expected_stop_timeout=5.0,
        expected_start_timeout=5.0, expected_old_pid_behavior="EXIT",
        expected_new_pid_behavior="NEW_PID_REQUIRED",
        expected_executable="/bin/svc", expected_user="hermes",
        expected_ports=(), risk_class="HIGH",
        restart_authority_enabled=False,
    )


class TestServiceClassRestriction:
    def test_only_aux_allowed(self):
        assert ALLOWED_CLASS == "HERMES_AUXILIARY"
        assert class_allowed("HERMES_AUXILIARY") is True

    def test_hard_deny_classes_rejected(self):
        for cls in HARD_DENY_CLASSES:
            assert class_allowed(cls) is False, f"{cls} must be denied"

    def test_unknown_rejected(self):
        assert class_allowed("UNKNOWN") is False
        assert class_allowed("MYSTERY") is False

    def test_registry_rejects_non_aux(self):
        reg = RestartRegistry()
        with pytest.raises(ValueError):
            reg.register(_mk("HERMES_CORE"))

    def test_default_registry_has_aux_canary(self):
        reg = default_registry()
        p = reg.get("hermes-aux-canary")
        assert p is not None
        assert p.service_class == "HERMES_AUXILIARY"