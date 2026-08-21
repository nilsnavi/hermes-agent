"""Test post-start identity: executable/user/cgroup must match expected."""
from agent.service_restart_canary.verify import post_start_check
from agent.service_restart_foundation.models import ProcessIdentity


def _old():
    return ProcessIdentity(pid=100, start_identity="si-old", executable="/h.py",
                           user="hermes", cgroup="cg")


def test_post_start_ok():
    old = _old()
    new = ProcessIdentity(pid=200, start_identity="si-new", executable="/h.py",
                          user="hermes", cgroup="cg")
    assert post_start_check(old, new, "/h.py", "hermes", "cg").ok is True


def test_wrong_executable():
    old = _old()
    new = ProcessIdentity(pid=200, start_identity="si-new", executable="/bin/evil",
                          user="hermes", cgroup="cg")
    assert post_start_check(old, new, "/h.py", "hermes", "cg").ok is False


def test_wrong_user():
    old = _old()
    new = ProcessIdentity(pid=200, start_identity="si-new", executable="/h.py",
                          user="root", cgroup="cg")
    assert post_start_check(old, new, "/h.py", "hermes", "cg").ok is False


def test_wrong_cgroup():
    old = _old()
    new = ProcessIdentity(pid=200, start_identity="si-new", executable="/h.py",
                          user="hermes", cgroup="other")
    assert post_start_check(old, new, "/h.py", "hermes", "cg").ok is False