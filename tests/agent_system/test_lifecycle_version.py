"""Phase 5 hardening: lifecycle version is kept in the DEFINITION version domain.

Registration tracks lifecycle.version from the definition version, so admission
can never silently mismatch a definition version with an older lifecycle counter.
"""

from agent.agent_runtime.lifecycle import AgentLifecycleStatus
from agent.agent_runtime.permissions import AgentPermissions
from agent.agent_runtime.registry import AgentDefinition

from agent.agent_system import SystemAgentRuntime


def test_lifecycle_version_matches_definition_on_registration():
    rt = SystemAgentRuntime()
    rt.register_system_agents()
    coding = rt.registry().latest("coding")
    lifecycle = rt.lifecycle("coding")
    assert lifecycle is not None
    assert lifecycle.version == coding.version == 1
    assert lifecycle.status is AgentLifecycleStatus.REGISTERED


def test_lifecycle_version_increments_on_transition():
    rt = SystemAgentRuntime()
    rt.register_system_agents()
    v1 = rt.lifecycle("coding").version  # type: ignore[reportOptionalMemberAccess]
    rt.transition("coding", AgentLifecycleStatus.READY)
    v2 = rt.lifecycle("coding").version  # type: ignore[reportOptionalMemberAccess]
    rt.transition("coding", AgentLifecycleStatus.ACTIVE)
    v3 = rt.lifecycle("coding").version  # type: ignore[reportOptionalMemberAccess]
    assert v1 == 1
    assert v2 == 2
    assert v3 == 3


def test_registry_reversioning_resyncs_lifecycle_version():
    # Register a v2 definition -> lifecycle is reset to the definition version
    # domain, never left behind on an older counter.
    rt = SystemAgentRuntime()
    rt.register_system_agents()
    assert rt.lifecycle("coding").version == 1  # type: ignore[reportOptionalMemberAccess]
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
    assert rt.registry().latest("coding").version == 2
    assert rt.lifecycle("coding").version == 2  # type: ignore[reportOptionalMemberAccess]


def test_lifecycle_version_survives_idempotent_reregistration():
    rt = SystemAgentRuntime()
    rt.register_system_agents()
    v_before = rt.lifecycle("coding").version  # type: ignore[reportOptionalMemberAccess]
    rt.transition("coding", AgentLifecycleStatus.READY)
    rt.register_system_agents()  # no new version -> no lifecycle reset
    lifecycle = rt.lifecycle("coding")
    assert lifecycle.version == v_before + 1  # type: ignore[reportOptionalMemberAccess]
    assert lifecycle.status is AgentLifecycleStatus.READY  # type: ignore[reportOptionalMemberAccess]