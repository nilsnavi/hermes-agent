"""Test port transition: owner changes; wrong owner -> FAIL."""
from agent.service_restart_canary.verify import port_check
from agent.service_restart_foundation.ports import PortVerdict, validate_port_transition


def test_port_owner_ok():
    assert port_check(owner_ok=True).ok is True


def test_port_wrong_owner():
    assert port_check(owner_ok=False).ok is False