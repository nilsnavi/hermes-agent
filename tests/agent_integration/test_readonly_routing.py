"""Read-only routing (Phase 6 §11, §23, §24): runtime-owned, enabled,
admissible, capability-matched; unknown health EXCLUDED; failed agent excluded."""

import pytest

from agent.agent_integration.capabilities import ReadOnlyCapability
from agent.agent_integration.readonly_routing import (
    NoReadOnlyRoute,
    ReadOnlyRouter,
)
from agent.agent_system import SystemAgentRuntime
from agent.agent_system.health import AgentAdmissionStatus
from agent.agent_runtime.lifecycle import AgentLifecycleStatus


def _runtime(*, ready: tuple[str, ...] = (), observed: tuple[str, ...] = ()):
    rt = SystemAgentRuntime()
    rt.register_system_agents()
    for agent_id in ready:
        rt.transition(agent_id, AgentLifecycleStatus.READY)
    for agent_id in observed:
        rt.observe(agent_id)
    return rt


def _admission(rt):
    return lambda agent_id: rt.admission_status(agent_id)


def test_router_picks_admissible_capability_matched_agent():
    rt = _runtime(ready=("monitoring",), observed=("monitoring",))
    router = ReadOnlyRouter(
        sealed_registry=rt, admission=_admission(rt), enabled={"monitoring", "research"}
    )
    route = router.route(required_capability=ReadOnlyCapability.READ_HEALTH)
    assert route is not None
    assert route.agent_id == "monitoring"
    assert route.capability is ReadOnlyCapability.READ_HEALTH


def test_router_excludes_not_admissible_agent():
    # monitoring registered but NOT ready/observed -> NOT_ADMISSIBLE -> excluded.
    rt = _runtime()  # nothing ready
    router = ReadOnlyRouter(
        sealed_registry=rt, admission=lambda a: rt.admission_status(a),
        enabled={"monitoring"},
    )
    route = router.route(required_capability=ReadOnlyCapability.READ_HEALTH)
    assert route is None  # unknown health -> exclude


def test_router_excludes_unknown_health():
    rt = _runtime(ready=("monitoring",), observed=("monitoring",))
    router = ReadOnlyRouter(
        sealed_registry=rt,
        admission=lambda a: (AgentAdmissionStatus.UNKNOWN, "no lifecycle provider"),
        enabled={"monitoring"},
    )
    assert router.route(required_capability=ReadOnlyCapability.READ_HEALTH) is None


def test_router_excludes_disabled_agent():
    rt = _runtime(ready=("monitoring",), observed=("monitoring",))
    router = ReadOnlyRouter(
        sealed_registry=rt, admission=_admission(rt), enabled={"research"}  # monitoring disabled
    )
    assert router.route(required_capability=ReadOnlyCapability.READ_HEALTH) is None


def test_router_never_selects_non_declaring_agent():
    rt = _runtime(
        ready=("research", "monitoring", "memory"),
        observed=("research", "monitoring", "memory"),
    )
    router = ReadOnlyRouter(
        sealed_registry=rt, admission=_admission(rt),
        enabled={"research", "monitoring", "memory"},
    )
    h = router.route(required_capability=ReadOnlyCapability.READ_HEALTH)
    m = router.route(required_capability=ReadOnlyCapability.READ_MEMORY_CONTEXT)
    assert h is not None and h.agent_id == "monitoring"
    assert m is not None and m.agent_id == "memory"


def test_router_failed_agent_exclusion_orch003():
    rt = _runtime(ready=("research", "coding"), observed=("research", "coding"))
    router = ReadOnlyRouter(
        sealed_registry=rt, admission=_admission(rt), enabled={"research", "coding"}
    )
    # 'research' must never be re-selected after it failed; coding is an
    # alternative that also declares READ_FILE_METADATA.
    route = router.route_with_failed_exclusion(
        required_capability=ReadOnlyCapability.READ_FILE_METADATA,
        failed_agent_id="research",
        alternatives={"research", "coding"},
    )
    assert route is not None
    assert route.agent_id == "coding"
    assert route.agent_id != "research"


def test_router_excludes_for_missing_declaration():
    rt = _runtime(ready=("monitoring",), observed=("monitoring",))
    router = ReadOnlyRouter(
        sealed_registry=rt, admission=_admission(rt), enabled={"monitoring"}
    )
    # research capability (read_text_resource) not offered by monitoring.
    assert router.route(required_capability=ReadOnlyCapability.READ_TEXT_RESOURCE) is None


def test_router_rejects_non_typed_capability():
    rt = _runtime()
    router = ReadOnlyRouter(sealed_registry=rt, admission=lambda a: (_admission(rt)(a)), enabled=set())
    with pytest.raises(NoReadOnlyRoute):
        router.route(required_capability="read_anything")  # type: ignore[arg-type]


def test_router_only_selects_never_grants():
    rt = _runtime(ready=("monitoring",), observed=("monitoring",))
    router = ReadOnlyRouter(
        sealed_registry=rt, admission=_admission(rt), enabled={"monitoring"}
    )
    route = router.route(required_capability=ReadOnlyCapability.READ_HEALTH)
    assert route is not None
    # Router returns only an agent id + metadata; no dispatch/execute/grant surface.
    assert route.agent_id == "monitoring"
    assert not hasattr(route, "dispatch")
    assert not hasattr(route, "execute")
    assert not hasattr(route, "grant")