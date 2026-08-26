"""Phase 5 hardening: runtime-owned registry allowlist, sealead against drift,
declared-but-not-granted enforcement, and canonical capability/permission checks.
"""

import pytest

from agent.agent_runtime.exceptions import AgentContractError
from agent.agent_runtime.permissions import AgentPermissions
from agent.agent_runtime.registry import AgentDefinition, AgentRegistry

from agent.agent_system import SystemAgentRuntime
from agent.agent_system.definitions import (
    SYSTEM_IMPLEMENTATION_IDS,
    build_system_agent_definitions,
)
from agent.agent_system.exceptions import AgentRegistryDrift, UnknownImplementation


def _canonical_definition() -> AgentDefinition:
    coding = [d for d in build_system_agent_definitions() if d.agent_id == "coding"][0]
    return coding


def test_registry_digest_is_deterministic_sha256():
    rt1 = SystemAgentRuntime()
    rt2 = SystemAgentRuntime()
    rt1.register_system_agents()
    rt2.register_system_agents()
    d1 = rt1.registry_digest()
    d2 = rt2.registry_digest()
    assert d1 == d2
    assert len(d1) == 64  # sha256 hex


def test_sealed_snapshot_detects_external_registry_mutation():
    rt = SystemAgentRuntime()
    rt.register_system_agents()
    sealed = rt.assert_registry_sealed()
    assert sealed == rt.registry_digest()

    # Mutate the underlying registry DIRECTLY (bypassing runtime re-sealing),
    # simulating a rebound/mutated registry. The old seal must flag REGISTRY_DRIFT.
    coding_v2 = AgentDefinition(
        agent_id="coding",
        version=2,
        name="Coding Agent",
        role="coding",
        implementation_id="coding-agent",
        capabilities=("coding_execution",),
        trust_score=0.75,
        permissions=AgentPermissions(read_files=True, agent_message_send=True),
    )
    rt.registry().register(coding_v2)
    assert rt.registry_digest() != sealed
    with pytest.raises(AgentRegistryDrift):
        rt.assert_registry_sealed()  # old seal no longer matches -> drift


def test_legitimate_re_registration_reseals_snapshot():
    # Registering through the runtime re-seals (no drift on the legitimate path).
    rt = SystemAgentRuntime()
    rt.register_system_agents()
    rt.assert_registry_sealed()
    coding_v2 = AgentDefinition(
        agent_id="coding",
        version=2,
        name="Coding Agent",
        role="coding",
        implementation_id="coding-agent",
        capabilities=("coding_execution",),
        trust_score=0.75,
        permissions=AgentPermissions(read_files=True, agent_message_send=True),
    )
    rt.register(coding_v2)
    # No drift after the runtime re-seals the (now-v2) snapshot.
    assert rt.assert_registry_sealed() == rt.registry_digest()


def test_registration_with_non_canonical_implementation_is_rejected():
    rt = SystemAgentRuntime()
    rogue = AgentDefinition(
        agent_id="evil",
        version=1,
        name="Evil",
        role="evil",
        implementation_id="evil-agent",
        capabilities=("analyze_code",),
        trust_score=0.5,
        permissions=AgentPermissions(read_files=True),
    )
    with pytest.raises(UnknownImplementation):
        rt.register(rogue)


def test_runtime_rejects_a_prepopulated_registry_with_non_canonical_impl():
    # Even if the caller hands in a registry that already holds a non-canonical
    # implementation, the runtime seals the allowlist at construction.
    rogue_registry = AgentRegistry(allowed_implementation_ids={"evil-impl", *SYSTEM_IMPLEMENTATION_IDS})
    rogue = AgentDefinition(
        agent_id="evil",
        version=1,
        name="Evil",
        role="evil",
        implementation_id="evil-impl",
        capabilities=("analyze_code",),
        trust_score=0.5,
        permissions=AgentPermissions(read_files=True),
    )
    rogue_registry.register(rogue)
    with pytest.raises(UnknownImplementation):
        SystemAgentRuntime(registry=rogue_registry)


def test_declared_capability_beyond_canonical_is_smuggling_denied():
    rt = SystemAgentRuntime()
    coding = _canonical_definition()
    smuggled = AgentDefinition(
        agent_id="coding",
        version=1,
        name=coding.name,
        role=coding.role,
        implementation_id=coding.implementation_id,
        capabilities=("coding_execution", "write_files"),  # beyond canonical set
        trust_score=coding.trust_score,
        permissions=coding.permissions,
    )
    with pytest.raises(AgentContractError):
        rt.register(smuggled)


def test_write_files_permission_is_hard_denied():
    rt = SystemAgentRuntime()
    coding = _canonical_definition()
    with_perms = AgentDefinition(
        agent_id="coding",
        version=1,
        name=coding.name,
        role=coding.role,
        implementation_id=coding.implementation_id,
        capabilities=coding.capabilities,
        trust_score=coding.trust_score,
        permissions=AgentPermissions(read_files=True, write_files=True),
    )
    with pytest.raises(AgentContractError):
        rt.register(with_perms)


def test_execute_code_permission_is_hard_denied():
    rt = SystemAgentRuntime()
    coding = _canonical_definition()
    with_exec = AgentDefinition(
        agent_id="coding",
        version=1,
        name=coding.name,
        role=coding.role,
        implementation_id=coding.implementation_id,
        capabilities=coding.capabilities,
        trust_score=coding.trust_score,
        permissions=AgentPermissions(read_files=True, execute_code=True),
    )
    with pytest.raises(AgentContractError):
        rt.register(with_exec)


def test_permission_beyond_canonical_is_denied():
    rt = SystemAgentRuntime()
    # Researcher canonical allows read_files+agent_message_send; grant network.
    research = [d for d in build_system_agent_definitions() if d.agent_id == "research"][0]
    over = AgentDefinition(
        agent_id="research",
        version=1,
        name=research.name,
        role=research.role,
        implementation_id=research.implementation_id,
        capabilities=research.capabilities,
        trust_score=research.trust_score,
        permissions=AgentPermissions(read_files=True, network_access=True),
    )
    with pytest.raises(AgentContractError):
        rt.register(over)


def test_unknown_agent_id_with_canonical_impl_is_denied():
    rt = SystemAgentRuntime()
    coding = _canonical_definition()
    rogue = AgentDefinition(
        agent_id="mystery",
        version=1,
        name="Mystery",
        role="mystery",
        implementation_id="coding-agent",  # canonical impl but alien agent_id
        capabilities=("coding_execution",),
        trust_score=0.75,
        permissions=AgentPermissions(read_files=True),
    )
    with pytest.raises(UnknownImplementation):
        rt.register(rogue)


def test_registry_never_expands_production_capabilities():
    rt = SystemAgentRuntime()
    rt.register_system_agents()
    # Every registered implementation belongs to the fixed system set.
    for definition in build_system_agent_definitions():
        assert definition.implementation_id in SYSTEM_IMPLEMENTATION_IDS


def test_register_is_idempotent_on_latest_version():
    rt = SystemAgentRuntime()
    rt.register_system_agents()
    before = rt.registry_digest()
    rt.register_system_agents()  # no version bump -> digest unchanged
    assert rt.registry_digest() == before