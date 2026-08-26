"""Agent Router tests."""

import pytest

from agent.agent_orchestration.router import AgentRouter, NoRoute
from agent.agent_runtime.permissions import AgentPermissions
from agent.agent_runtime.registry import AgentDefinition, AgentRegistry


def _definition(agent_id, *, capabilities, trust=0.8, implementation="impl-x"):
    return AgentDefinition(
        agent_id=agent_id,
        version=1,
        name=agent_id,
        role="agent",
        implementation_id=implementation,
        capabilities=capabilities,
        trust_score=trust,
        permissions=AgentPermissions(read_files=True),
    )


def _router(defs):
    registry = AgentRegistry(allowed_implementation_ids={"impl-x"})
    for definition in defs:
        registry.register(definition)
    return AgentRouter(registry)


def test_route_selects_capable_agent():
    router = _router([
        _definition("read", capabilities=("file_read",)),
        _definition("write", capabilities=("file_write",)),
    ])
    selection = router.route(required_capability="file_read")
    assert selection.agent_id == "read"


def test_route_raises_when_no_capability():
    router = _router([
        _definition("read", capabilities=("file_read",)),
    ])
    with pytest.raises(NoRoute):
        router.route(required_capability="file_write")


def test_route_availability_gate():
    router = _router([
        _definition("a", capabilities=("file_read",)),
        _definition("b", capabilities=("file_read",)),
    ])
    selection = router.route(required_capability="file_read", availability={"b"})
    assert selection.agent_id == "b"


def test_route_excludes_zero_trust():
    router = _router([
        _definition("untrusted", capabilities=("file_read",), trust=0.0),
    ])
    with pytest.raises(NoRoute):
        router.route(required_capability="file_read")


def test_route_deterministic_tiebreak():
    router = _router([
        _definition("b", capabilities=("file_read",)),
        _definition("a", capabilities=("file_read",)),
    ])
    # Same score -> tie-break by agent_id ascending -> "a".
    assert router.route(required_capability="file_read").agent_id == "a"


def test_router_has_no_execution_surface():
    router = _router([_definition("a", capabilities=("file_read",))])
    assert not hasattr(router, "execute")
    assert not hasattr(router, "run")
    assert not hasattr(router, "dispatch")
    assert not hasattr(router, "authorize")


def test_route_rejects_empty_capability():
    router = _router([_definition("a", capabilities=("file_read",))])
    with pytest.raises(NoRoute):
        router.route(required_capability="  ")