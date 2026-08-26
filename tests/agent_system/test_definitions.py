"""System agent definitions tests: descriptive metadata, no mutation surface."""

import pytest

from agent.agent_runtime.exceptions import AgentContractError
from agent.agent_runtime.registry import AgentRegistry

from agent.agent_system.definitions import (
    SYSTEM_IMPLEMENTATION_IDS,
    SystemAgentRole,
    build_system_agent_definitions,
    system_agent_definition,
    system_agent_role,
)
from agent.agent_system import SystemCapability


def test_six_mvp_system_agents():
    defs = build_system_agent_definitions()
    assert len(defs) == 6
    ids = {d.agent_id for d in defs}
    assert ids == {"planner", "research", "coding", "reviewer", "memory", "monitoring"}


def test_all_version_one_unique_ids():
    defs = build_system_agent_definitions()
    assert all(d.version == 1 for d in defs)
    assert len({d.agent_id for d in defs}) == 6


def test_planner_declares_planning_and_coordination():
    d = system_agent_definition(SystemAgentRole.PLANNER)
    assert SystemCapability.PLANNING.value in d.capabilities
    assert SystemCapability.COORDINATION.value in d.capabilities


def test_coding_mutation_disabled_this_phase():
    d = system_agent_definition(SystemAgentRole.CODING)
    assert d.permissions.write_files is False
    assert d.permissions.execute_code is False
    # CodingAgent is declared for coding but the write/execute grant is OFF:
    # a declaration is metadata, not the ability to mutate.
    assert SystemCapability.CODING_EXECUTION.value in d.capabilities


def test_memory_agent_only_proposes():
    d = system_agent_definition(SystemAgentRole.MEMORY)
    assert d.permissions.memory_write is False
    assert SystemCapability.MEMORY_PROPOSAL.value in d.capabilities


def test_research_is_read_only_surface():
    d = system_agent_definition(SystemAgentRole.RESEARCH)
    assert d.permissions.write_files is False
    assert d.permissions.execute_code is False


def test_definitions_carry_no_executable_surface():
    d = system_agent_definition(SystemAgentRole.REVIEWER)
    for method in ("grant", "authorize", "execute", "dispatch", "run"):
        assert not hasattr(d, method), f"definition must not expose {method}"


def test_trust_scores_allow_routing():
    for role in SystemAgentRole:
        assert system_agent_definition(role).trust_score > 0


def test_registry_allowlist_excludes_non_system_impl():
    reg = AgentRegistry(allowed_implementation_ids=SYSTEM_IMPLEMENTATION_IDS)
    from agent.agent_runtime.permissions import AgentPermissions
    from agent.agent_runtime.registry import AgentDefinition

    rogue = AgentDefinition(
        agent_id="rogue",
        version=1,
        name="rogue",
        role="rogue",
        implementation_id="not-a-system-agent",
        capabilities=("planning",),
        trust_score=0.9,
        permissions=AgentPermissions(execute_code=True),
    )
    with pytest.raises(AgentContractError):
        reg.register(rogue)


def test_system_agents_register_into_empty_registry():
    reg = AgentRegistry(allowed_implementation_ids=SYSTEM_IMPLEMENTATION_IDS)
    for d in build_system_agent_definitions():
        reg.register(d)
    assert len(reg.list()) == 6


def test_system_agent_role_mapping():
    assert system_agent_role("planner") is SystemAgentRole.PLANNER
    with pytest.raises(ValueError):
        system_agent_role("ghost")


def test_system_agent_definition_rejects_wrong_role_type():
    with pytest.raises(ValueError):
        system_agent_definition("planner")  # type: ignore[arg-type]