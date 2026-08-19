"""Sprint 1.3.12 — PID transition model (test_pid_transition.py).

Restart success requires new_pid != old_pid (unless contract proves otherwise).
PID reuse must be detected via PID + process-start identity, not PID alone.
"""
from __future__ import annotations

from agent.service_restart_foundation.models import ProcessIdentity
from agent.service_restart_foundation.pid_transition import (
    TransitionVerdict,
    validate_transition,
)


def _old():
    return ProcessIdentity(pid=100, start_identity="boot-1",
                           executable="/usr/bin/handler.py", user="hermes",
                           cgroup="cgroup-a", unit="hermes-aux-canary.service")


def _new(pid=200, start="boot-2"):
    return ProcessIdentity(pid=pid, start_identity=start,
                           executable="/usr/bin/handler.py", user="hermes",
                           cgroup="cgroup-a", unit="hermes-aux-canary.service")


class TestPidTransitionValidation:
    def test_new_pid_different_ok(self):
        assert validate_transition(_old(), _new()).verdict == TransitionVerdict.PASS

    def test_old_pid_survives_fails(self):
        # old PID = new PID -> invalid, must not be treated as success
        assert validate_transition(_old(), _new(pid=100)).verdict == TransitionVerdict.FAIL

    def test_pid_reuse_with_different_start_identity_fails(self):
        v = validate_transition(_old(), _new(pid=100, start="boot-3"))
        assert v.verdict == TransitionVerdict.FAIL
        assert v.pid_reuse_detected is True

    def test_executable_changed_fails(self):
        bad = ProcessIdentity(200, "boot-2", "/usr/bin/evil.py", "hermes",
                              "cgroup-a", "hermes-aux-canary.service")
        assert validate_transition(_old(), bad).verdict == TransitionVerdict.FAIL

    def test_user_changed_fails(self):
        bad = ProcessIdentity(200, "boot-2", "/usr/bin/handler.py", "root",
                              "cgroup-a", "hermes-aux-canary.service")
        assert validate_transition(_old(), bad).verdict == TransitionVerdict.FAIL

    def test_cgroup_changed_fails(self):
        bad = ProcessIdentity(200, "boot-2", "/usr/bin/handler.py", "hermes",
                              "cgroup-b", "hermes-aux-canary.service")
        assert validate_transition(_old(), bad).verdict == TransitionVerdict.FAIL

    def test_new_start_identity_required(self):
        bad = ProcessIdentity(200, "", "/usr/bin/handler.py", "hermes",
                              "cgroup-a", "hermes-aux-canary.service")
        assert validate_transition(_old(), bad).verdict == TransitionVerdict.FAIL

    def test_unknown_start_state(self):
        from agent.service_restart_foundation.pid_transition import verify_start
        assert verify_start(_old(), None) == "START_UNKNOWN"