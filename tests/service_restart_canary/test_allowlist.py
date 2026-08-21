"""Test exact allowlist: only hermes-aux-canary.service, no glob/regex."""
from agent.service_restart_canary.allowlist import (
    CANARY_SERVICE_ID, CANARY_UNIT, default_allowlist, RestartAllowlist,
    RestartAllowlistEntry,
)


def test_canary_registered():
    al = default_allowlist()
    assert al.contains_service(CANARY_SERVICE_ID)
    assert al.contains_unit(CANARY_UNIT)


def test_entry_fields():
    al = default_allowlist()
    e = al.entry_for_service(CANARY_SERVICE_ID)
    assert e is not None
    assert e.service_id == "hermes-aux-canary"
    assert e.unit_name == "hermes-aux-canary.service"
    assert e.expected_user == "hermes"
    assert e.expected_executable.endswith("handler.py")
    assert e.restart_contract_version == 1


def test_unregistered_service_denied():
    al = default_allowlist()
    assert not al.contains_service("ghost")
    assert not al.contains_service("hermes-gateway")
    assert not al.contains_service("hermes-scheduler")


def test_unregistered_unit_denied():
    al = default_allowlist()
    assert not al.contains_unit("ghost.service")
    assert not al.contains_unit("hermes-gateway.service")


def test_no_glob_or_regex():
    al = default_allowlist()
    assert not al.contains_service("hermes-aux")
    assert not al.contains_unit("hermes-aux-canary.servicex")


def test_exact_one_entry():
    al = default_allowlist()
    assert len(al.exact()) == 1


def test_custom_allowlist():
    e = RestartAllowlistEntry(service_id="x", unit_name="x.service")
    al = RestartAllowlist(entries=(e,))
    assert al.contains_service("x")
    assert not al.contains_service("hermes-aux-canary")
