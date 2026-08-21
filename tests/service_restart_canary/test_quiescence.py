"""Test quiescence: QUIESCENT required before declaring success.
Uses the foundation's quiescence observation contract keys.
"""
from agent.service_restart_canary.verify import quiescence_check
from agent.service_restart_foundation.quiescence import QuiescenceResult


def test_quiescent_ok():
    r = quiescence_check({"old_pid_present": False, "children": (), "port_owners": {}})
    assert r.ok is True


def test_not_quiescent_old_pid():
    r = quiescence_check({"old_pid_present": True, "children": (), "port_owners": {}})
    assert r.ok is False


def test_not_quiescent_children():
    r = quiescence_check({"old_pid_present": False, "children": ("child1",), "port_owners": {}})
    assert r.ok is False


def test_not_quiescent_ports():
    r = quiescence_check({"old_pid_present": False, "children": (),
                          "port_owners": {"9000": 123}})
    assert r.ok is False


def test_unknown_is_not_ok():
    r = quiescence_check({"old_pid_present": None})
    assert r.ok is False