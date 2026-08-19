"""Sprint 1.3.12 — port transition + stop/start contract + post-start identity.

Port transition: expected listener owned by old service identity -> disappears on
stop -> reappears owned by new verified PID after start. Wrong PID owns port = FAIL.
Unexpected public listener -> risk up / DENY.
"""
from __future__ import annotations

from agent.service_restart_foundation.ports import PortVerdict, validate_port_transition
from agent.service_restart_foundation.stop_contract import StopState, StopVerdict, evaluate_stop
from agent.service_restart_foundation.start_contract import StartVerdict, evaluate_start
from agent.service_restart_foundation.identity_after_start import verify_post_start_identity


class TestPortTransition:
    def test_listener_returns_to_new_pid_ok(self):
        v = validate_port_transition(
            service_id="hermes-aux-canary",
            ports=("127.0.0.1:8080",),
            old_owner="100",
            new_owner="200",
            unexpected_listeners=(),
        )
        assert v.verdict == PortVerdict.PASS

    def test_wrong_pid_owns_port_fails(self):
        v = validate_port_transition(
            service_id="hermes-aux-canary",
            ports=("127.0.0.1:8080",),
            old_owner="100",
            new_owner="999",  # wrong pid owns it
            unexpected_listeners=(),
        )
        assert v.verdict == PortVerdict.FAIL

    def test_unexpected_public_listener_fails(self):
        v = validate_port_transition(
            service_id="hermes-aux-canary",
            ports=("127.0.0.1:8080",),
            old_owner="100",
            new_owner="200",
            unexpected_listeners=("0.0.0.0:9000",),
        )
        assert v.verdict == PortVerdict.DENY

    def test_port_never_released_fails(self):
        v = validate_port_transition(
            service_id="hermes-aux-canary",
            ports=("127.0.0.1:8080",),
            old_owner="100",
            new_owner="100",  # old owner still holds -> not released
            unexpected_listeners=(),
        )
        assert v.verdict == PortVerdict.FAIL


class TestStopContract:
    def test_normal_stop_ok(self):
        v = evaluate_stop(
            current="active",
            expected_path=("active", "deactivating", "inactive"),
            reached="inactive",
            timeout_ok=True,
            old_pid_gone=True,
        )
        assert v.verdict == StopVerdict.STOPPED
        assert v.state == StopState.STOPPED

    def test_stop_timeout_unknown(self):
        v = evaluate_stop(
            current="deactivating", expected_path=("active", "deactivating", "inactive"),
            reached="deactivating", timeout_ok=False, old_pid_gone=True,
        )
        assert v.verdict == StopVerdict.UNKNOWN
        assert v.state == StopState.STOP_UNKNOWN

    def test_old_pid_remains_fails(self):
        v = evaluate_stop(
            current="inactive", expected_path=("active", "deactivating", "inactive"),
            reached="inactive", timeout_ok=True, old_pid_gone=False,
        )
        assert v.verdict == StopVerdict.FAIL


class TestStartContract:
    def test_started_verified(self):
        v = evaluate_start(
            new_pid=200, new_pid_required=True,
            expected_executable="/usr/bin/handler.py", actual_executable="/usr/bin/handler.py",
            expected_user="hermes", actual_user="hermes",
            unit="active", expected_unit="active",
            warmup_ok=True, health_ok=True,
        )
        assert v.verdict == StartVerdict.STARTED_VERIFIED

    def test_start_failed_no_pid(self):
        v = evaluate_start(
            new_pid=None, new_pid_required=True,
            expected_executable="/usr/bin/handler.py", actual_executable="",
            expected_user="hermes", actual_user="",
            unit="inactive", expected_unit="active",
            warmup_ok=False, health_ok=False,
        )
        assert v.verdict == StartVerdict.START_FAILED

    def test_start_unknown_timeout(self):
        v = evaluate_start(
            new_pid=200, new_pid_required=True,
            expected_executable="/usr/bin/handler.py", actual_executable="/usr/bin/handler.py",
            expected_user="hermes", actual_user="hermes",
            unit="activating", expected_unit="active",
            warmup_ok=False, health_ok=False, unknown=True,
        )
        assert v.verdict == StartVerdict.START_UNKNOWN


class TestIdentityAfterStart:
    def test_identity_matches(self):
        r = verify_post_start_identity(
            expected_executable="/usr/bin/handler.py", actual_executable="/usr/bin/handler.py",
            expected_user="hermes", actual_user="hermes",
            expected_cgroup="cg-a", actual_cgroup="cg-a", new_pid=200,
        )
        assert r is True

    def test_executable_flag_identity_mismatch_fails(self):
        r = verify_post_start_identity(
            expected_executable="/usr/bin/handler.py", actual_executable="/usr/bin/evil.py",
            expected_user="hermes", actual_user="hermes",
            expected_cgroup="cg-a", actual_cgroup="cg-a", new_pid=200,
        )
        assert r is False

    def test_user_mismatch_fails(self):
        r = verify_post_start_identity(
            expected_executable="/usr/bin/handler.py", actual_executable="/usr/bin/handler.py",
            expected_user="hermes", actual_user="root",
            expected_cgroup="cg-a", actual_cgroup="cg-a", new_pid=200,
        )
        assert r is False