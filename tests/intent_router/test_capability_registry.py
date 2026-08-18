"""Sprint 1.3.0 §32 — Capability Registry tests."""

import pytest

from agent.capability_router.capabilities import Capability
from agent.capability_router.models import CapabilityDescriptor
from agent.capability_router.registry import (
    DEFAULT_DESCRIPTORS,
    CapabilityRegistry,
    RegistryValidationError,
)


def _reg():
    return CapabilityRegistry()


# ── §32 registry surface ───────────────────────────────────────────


def test_registry_contains_status_capabilities():
    """The six-capability surface: all five STATUS_* entries."""
    reg = _reg()
    for cap in (
        Capability.STATUS_RUNTIME,
        Capability.STATUS_GATEWAY,
        Capability.STATUS_INTEGRATION,
        Capability.STATUS_SCHEDULER,
        Capability.STATUS_PROVIDER,
    ):
        assert reg.has(cap), f"{cap.value} missing"
    assert "STATUS_RUNTIME" in reg.names()
    assert "STATUS_GATEWAY" in reg.names()
    assert "STATUS_INTEGRATION" in reg.names()
    assert "STATUS_SCHEDULER" in reg.names()
    assert "STATUS_PROVIDER" in reg.names()


def test_registry_contains_operational_search():
    """OPERATIONAL_SEARCH is registered with the verified search tool."""
    reg = _reg()
    assert reg.has(Capability.OPERATIONAL_SEARCH)
    assert reg.tool_for(Capability.OPERATIONAL_SEARCH) == \
        "operational_log_search"
    assert "operational_log_search" in reg.tools()


def test_registry_tools_match_canonical_map():
    """Every canonical tool exists in the verified tool surface."""
    reg = _reg()
    assert set(reg.tools()) == {
        "runtime_status", "gateway_status", "integration_status",
        "scheduler_status", "provider_status", "operational_log_search",
    }


# ── §27 validation ─────────────────────────────────────────────────


def test_registry_rejects_duplicate_capability():
    """Duplicate capability registration → error at construction."""
    with pytest.raises(RegistryValidationError):
        CapabilityRegistry(
            descriptors=[
                *DEFAULT_DESCRIPTORS,
                CapabilityDescriptor(
                    capability=Capability.STATUS_RUNTIME,
                    tool_name="runtime_status",
                ),
            ],
        )


def test_registry_rejects_duplicate_tool_mapping():
    """Two capabilities mapped to the same production tool → error."""
    with pytest.raises(RegistryValidationError):
        CapabilityRegistry(
            descriptors=[
                CapabilityDescriptor(
                    capability=Capability.STATUS_RUNTIME,
                    tool_name="runtime_status",
                ),
                CapabilityDescriptor(
                    capability=Capability.STATUS_GATEWAY,
                    tool_name="runtime_status",  # duplicate tool
                ),
            ],
        )


def test_registry_rejects_unverified_route():
    """An unverified routed capability is a §27 error."""
    with pytest.raises(RegistryValidationError):
        CapabilityRegistry(
            descriptors=[
                CapabilityDescriptor(
                    capability=Capability.STATUS_RUNTIME,
                    tool_name="runtime_status",
                    verified=False,
                ),
            ],
        )


def test_registry_rejects_risk_mismatch():
    """READ_ONLY capability mapped to a write tool → error."""
    with pytest.raises(RegistryValidationError):
        CapabilityRegistry(
            descriptors=[
                CapabilityDescriptor(
                    capability=Capability.STATUS_RUNTIME,
                    tool_name="runtime_status",
                    side_effect="IRREVERSIBLE_WRITE",  # lies about the tool
                ),
            ],
        )


def test_registry_rejects_network_violation():
    """A LOCAL_ONLY capability mapped to a network tool → error."""
    with pytest.raises(RegistryValidationError):
        CapabilityRegistry(
            descriptors=[
                CapabilityDescriptor(
                    capability=Capability.OPERATIONAL_SEARCH,
                    tool_name="operational_log_search",
                    network=True,  # contract says local only
                ),
            ],
        )


def test_registry_rejects_unknown_tool():
    """A tool with no verified legacy contract → error (no dynamic
    tool discovery: an undeclared tool can never enter the surface)."""
    with pytest.raises(RegistryValidationError):
        CapabilityRegistry(
            descriptors=[
                CapabilityDescriptor(
                    capability=Capability.STATUS_RUNTIME,
                    tool_name="brand_new_tool",
                ),
            ],
        )
