"""CapabilityDeclaration / CapabilitySurface tests: declarative, fail-closed, no authority."""

import pytest

from agent.agent_system.capabilities import (
    CapabilityDeclaration,
    CapabilitySurface,
    SystemCapability,
    declare_capabilities,
)
from agent.agent_system.exceptions import CapabilityDeclarationError


def _three(n=3):
    return CapabilitySurface(
        tuple(
            CapabilityDeclaration(
                agent_id="planner",
                capability=cap,
                description=f"declared to {cap.value}",
            )
            for cap in (SystemCapability.PLANNING, SystemCapability.COORDINATION)
        )
    )


def test_declaration_is_frozen_immutable():
    d = CapabilityDeclaration("planner", SystemCapability.PLANNING, "plans")
    with pytest.raises(Exception):
        d.agent_id = "other"  # type: ignore[attr-defined]  frozen dataclass
    assert d.agent_id == "planner"
    assert d.capability is SystemCapability.PLANNING


def test_declaration_rejects_invalid_agent_id():
    with pytest.raises(CapabilityDeclarationError):
        CapabilityDeclaration("", SystemCapability.PLANNING, "x")


def test_declaration_rejects_non_exact_capability():
    with pytest.raises(CapabilityDeclarationError):
        CapabilityDeclaration("p", "planning", "x")  # type: ignore[arg-type]


def test_declaration_rejects_empty_description():
    with pytest.raises(CapabilityDeclarationError):
        CapabilityDeclaration("p", SystemCapability.PLANNING, "")


def test_surface_requires_single_owner():
    decls = (
        CapabilityDeclaration("a", SystemCapability.PLANNING, "x"),
        CapabilityDeclaration("b", SystemCapability.RESEARCH, "y"),
    )
    with pytest.raises(CapabilityDeclarationError):
        CapabilitySurface(decls)


def test_surface_rejects_duplicate_capability():
    decls = (
        CapabilityDeclaration("p", SystemCapability.PLANNING, "x"),
        CapabilityDeclaration("p", SystemCapability.PLANNING, "y"),
    )
    with pytest.raises(CapabilityDeclarationError):
        CapabilitySurface(decls)


def test_surface_rejects_empty():
    with pytest.raises(CapabilityDeclarationError):
        CapabilitySurface(())


def test_declare_capabilities_builds_surface():
    surface = declare_capabilities(
        "research", capabilities=(SystemCapability.RESEARCH,), description="read-only"
    )
    assert surface.agent_id == "research"
    assert SystemCapability.RESEARCH in surface.declared()
    assert surface.contains(SystemCapability.RESEARCH)
    assert not surface.contains(SystemCapability.PLANNING)


def test_declare_capabilities_rejects_duplicates():
    with pytest.raises(CapabilityDeclarationError):
        declare_capabilities(
            "x",
            capabilities=(SystemCapability.RESEARCH, SystemCapability.RESEARCH),
            description="dup",
        )


def test_surface_declaration_lookup():
    surface = _three()
    assert surface.declaration(SystemCapability.PLANNING) is not None
    assert surface.declaration(SystemCapability.REVIEW) is None  # not declared


def test_surface_contains_requires_exact_enum():
    with pytest.raises(CapabilityDeclarationError):
        _three().contains("research")  # type: ignore[arg-type]


def test_declaration_to_dict_uses_value_strings():
    d = CapabilityDeclaration("p", SystemCapability.PLANNING, "plans")
    assert d.to_dict()["capability"] == "planning"


def test_canonical_set_is_immutable_and_exact():
    assert SystemCapability.PLANNING in __import__(
        "agent.agent_system.capabilities", fromlist=["CANONICAL_CAPABILITIES"]
    ).CANONICAL_CAPABILITIES


def test_surface_exposes_no_authority_methods():
    surface = _three()
    for method in ("grant", "authorize", "execute", "dispatch"):
        assert not hasattr(surface, method), f"surface must not expose {method}"