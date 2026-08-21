"""Test PID transition: old identity must disappear; PID reuse detected."""
from agent.service_restart_canary.verify import old_identity_gone, new_identity_verified
from agent.service_restart_foundation.models import ProcessIdentity
from agent.service_restart_foundation.pid_transition import validate_transition, TransitionVerdict


def _old():
    return ProcessIdentity(pid=100, start_identity="si-old", executable="/h.py", user="hermes", cgroup="cg")


def test_old_identity_gone_pid_reused():
    old = _old()
    cur = ProcessIdentity(pid=100, start_identity="si-new", executable="/h.py", user="hermes", cgroup="cg")
    # same PID but new start identity -> old identity gone (transition is fine)
    assert old_identity_gone(old, cur).ok is True


def test_old_identity_survives():
    old = _old()
    cur = ProcessIdentity(pid=100, start_identity="si-old", executable="/h.py", user="hermes", cgroup="cg")
    assert old_identity_gone(old, cur).ok is False


def test_no_current_process():
    assert old_identity_gone(_old(), None).ok is False


def test_new_identity_verified():
    old = _old()
    new = ProcessIdentity(pid=200, start_identity="si-new", executable="/h.py", user="hermes", cgroup="cg")
    assert new_identity_verified(old, new).ok is True


def test_new_identity_reuse_fails():
    old = _old()
    new = ProcessIdentity(pid=100, start_identity="si-old", executable="/h.py", user="hermes", cgroup="cg")
    assert new_identity_verified(old, new).ok is False


def test_wrong_executable():
    old = _old()
    new = ProcessIdentity(pid=200, start_identity="si-new", executable="/bin/evil", user="hermes", cgroup="cg")
    assert new_identity_verified(old, new).ok is False