"""Sprint 1.3.12 — restart profile + authority model (test_models.py).

Restart profile is immutable, restart_authority_enabled=False always in 1.3.12.
Restart authority is a SEPARATE contract — never derived from reload authority.
"""
from __future__ import annotations

import pytest

from agent.service_restart_foundation.models import (
    ProcessIdentity,
    RestartProfile,
    RestartTransition,
    StopState,
    StartState,
)


def _profile(**kw) -> RestartProfile:
    base = dict(
        service_id="hermes-aux-canary",
        profile_version=1,
        unit_name="hermes-aux-canary.service",
        service_class="HERMES_AUXILIARY",
        criticality="LOW",
        restart_supported=True,
        expected_stop_timeout=10.0,
        expected_start_timeout=10.0,
        expected_old_pid_behavior="EXIT",
        expected_new_pid_behavior="NEW_PID_REQUIRED",
        expected_executable="/usr/bin/handler.py",
        expected_user="hermes",
        expected_ports=("127.0.0.1:8080",),
        quiescence_policy="REQUIRE_FULL_QUIESCENCE",
        startup_contract_id="default",
        health_contract_id="default",
        rollback_strategy="RECONCILE_CURRENT_STATE",
        risk_class="HIGH",
        blast_radius_ceiling="SERVICE",
        restart_authority_enabled=False,
    )
    base.update(kw)
    return RestartProfile(**base)


class TestRestartProfile:
    def test_profile_is_immutable_dataclass(self):
        p = _profile()
        with pytest.raises(Exception):  # noqa: B017 (frozen dataclass -> FrozenInstanceError/AttributeError)
            p.service_id = "x"

    def test_restart_authority_disabled_by_default(self):
        p = _profile()
        assert p.restart_authority_enabled is False

    def test_restart_authority_forced_false_via_property(self):
        # even if caller sets true at construction, the bound property is False in 1.3.12
        p = _profile(restart_authority_enabled=True)
        assert p.restart_authority_enabled is False

    def test_exec_cmd_fields_absent(self):
        # Sprint 1.3.12 has NO production restart adapter -> no raw exec fields on profile
        p = _profile()
        assert not hasattr(p, "restart_command")
        assert not hasattr(p, "stop_command")
        assert not hasattr(p, "start_command")

    def test_expected_fields_present(self):
        p = _profile()
        assert p.expected_stop_timeout == 10.0
        assert p.expected_start_timeout == 10.0
        assert p.expected_old_pid_behavior == "EXIT"
        assert p.expected_new_pid_behavior == "NEW_PID_REQUIRED"
        assert p.quiescence_policy == "REQUIRE_FULL_QUIESCENCE"
        assert p.rollback_strategy == "RECONCILE_CURRENT_STATE"


class TestProcessIdentity:
    def test_identity_binds_pid_and_start_identity(self):
        a = ProcessIdentity(pid=100, start="s1", executable="/usr/bin/x", user="hermes")
        b = ProcessIdentity(pid=200, start="s2", executable="/usr/bin/x", user="hermes")
        assert a.pid != b.pid
        assert a.start_identity != b.start_identity

    def test_same_pid_different_start_identity_is_different_process(self):
        # PID reuse must be caught by process-start identity, not just PID
        a = ProcessIdentity(pid=100, start="boot-1", executable="/usr/bin/x", user="hermes")
        b = ProcessIdentity(pid=100, start="boot-2", executable="/usr/bin/x", user="hermes")
        assert (a == b) is False
        assert a.same_process(b) is False

    def test_same_process_true_only_when_pid_and_start_identity_equal(self):
        a = ProcessIdentity(pid=100, start="s", executable="/usr/bin/x", user="hermes")
        b = ProcessIdentity(pid=100, start="s", executable="/usr/bin/x", user="hermes")
        assert a.same_process(b) is True


class TestRestartTransition:
    def test_success_requires_new_pid_different_from_old(self):
        t = RestartTransition(
            old=ProcessIdentity(100, "old", "/usr/bin/x", "hermes"),
            new=ProcessIdentity(200, "new", "/usr/bin/x", "hermes"),
        )
        assert t.new_pid_changed() is True

    def test_pid_reuse_not_success(self):
        t = RestartTransition(
            old=ProcessIdentity(100, "old", "/usr/bin/x", "hermes"),
            new=ProcessIdentity(100, "new", "/usr/bin/x", "hermes"),  # pid reused
        )
        assert t.new_pid_changed() is False  # same PID -> not a real transition


class TestStopStartModels:
    def test_stop_state_enum(self):
        assert StopState.STOPPED.value == "stopped"
        assert StopState.STOP_UNKNOWN.value == "stop_unknown"
        assert StopState.STOP_REQUESTED.value == "stop_requested"

    def test_start_state_enum(self):
        assert StartState.STARTED_VERIFIED.value == "started_verified"
        assert StartState.START_UNKNOWN.value == "start_unknown"