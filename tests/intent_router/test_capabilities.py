"""Capability registry tests (Sprint 1.1 §22-25, §66)."""

import pytest

from agent.intent_router.capabilities import (
    INTENT_CAPABILITIES,
    VERIFIED_V2_CAPABILITIES,
    CapabilityRegistry,
)
from agent.intent_router.exceptions import CapabilityUnknownError
from agent.intent_router.models import IntentType


def test_verified_surface_read_only_only():
    # Only production-safe capabilities are claimed (§24).
    for name in VERIFIED_V2_CAPABILITIES:
        assert name in ("READ_RUNTIME_STATUS",)


def test_no_write_capabilities_declared():
    assert "WRITE" not in VERIFIED_V2_CAPABILITIES
    assert "DELETE" not in VERIFIED_V2_CAPABILITIES
    assert "SYSTEM_CONTROL" not in VERIFIED_V2_CAPABILITIES


def test_status_read_requires_runtime_status():
    reg = CapabilityRegistry()
    assert reg.required_for(IntentType.STATUS_READ) == ["READ_RUNTIME_STATUS"]
    assert reg.capabilities_satisfied(["READ_RUNTIME_STATUS"]) is True


def test_capability_missing_for_search():
    reg = CapabilityRegistry()
    reqs = reg.required_for(IntentType.SEARCH_READ)
    assert reg.capabilities_satisfied(reqs) is False  # empty → missing


def test_write_intent_not_satisfiable():
    reg = CapabilityRegistry()
    reqs = reg.required_for(IntentType.WRITE_ACTION)
    assert reg.capabilities_satisfied(reqs) is False


def test_tools_for_capability():
    reg = CapabilityRegistry()
    tools = reg.tools_for_capability("READ_RUNTIME_STATUS")
    assert "runtime_status" in tools
    assert "canary_ping" in tools


def test_unknown_capability_raises():
    reg = CapabilityRegistry()
    with pytest.raises(CapabilityUnknownError):
        reg.tools_for_capability("WRITE")


def test_capability_gap():
    reg = CapabilityRegistry()
    gap = reg.capability_gap(["READ_RUNTIME_STATUS", "WRITE"])
    assert gap == ["WRITE"]


def test_register_new_capability():
    reg = CapabilityRegistry()
    reg.register("SEARCH", "future search surface")
    assert reg.has("SEARCH")


def test_intent_capability_map_complete():
    # Every IntentType has an entry (possibly empty = not satisfiable).
    for intent in IntentType:
        assert intent in INTENT_CAPABILITIES
