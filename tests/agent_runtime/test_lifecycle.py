"""Agent lifecycle state machine tests."""

import pytest

from agent.agent_runtime.exceptions import AgentContractError
from agent.agent_runtime.lifecycle import (
    AgentLifecycle,
    AgentLifecycleStatus,
)


def test_new_lifecycle_starts_registered():
    lifecycle = AgentLifecycle()
    assert lifecycle.status is AgentLifecycleStatus.REGISTERED
    assert lifecycle.version == 0
    assert lifecycle.history == ()


def test_registered_readies_then_activates():
    lifecycle = AgentLifecycle()
    ready = lifecycle.transition(AgentLifecycleStatus.READY)
    active = ready.transition(AgentLifecycleStatus.ACTIVE)
    assert active.status is AgentLifecycleStatus.ACTIVE
    assert active.version == 2
    assert len(active.history) == 2


def test_illegal_skip_transition_raises():
    lifecycle = AgentLifecycle()
    with pytest.raises(AgentContractError):
        lifecycle.transition(AgentLifecycleStatus.ACTIVE)


def test_is_terminal_for_retired():
    lifecycle = AgentLifecycle(
        status=AgentLifecycleStatus.RETIRED, version=1,
        history=(),
    )
    assert lifecycle.is_terminal
    # No forward transition out of a terminal state.
    assert not lifecycle.can_transition_to(AgentLifecycleStatus.ACTIVE)


def test_disabled_is_terminal_and_no_flapping():
    disabled = AgentLifecycle().transition(AgentLifecycleStatus.READY).transition(
        AgentLifecycleStatus.ACTIVE
    ).transition(AgentLifecycleStatus.DISABLED)
    assert disabled.is_terminal
    # Re-enabling a disabled agent is NOT a direct lifecycle transition.
    with pytest.raises(AgentContractError):
        disabled.transition(AgentLifecycleStatus.ACTIVE)


def test_retire_from_ready_or_disabled():
    ready = AgentLifecycle().transition(AgentLifecycleStatus.READY)
    assert ready.transition(AgentLifecycleStatus.RETIRED).is_terminal

    disabled = (
        AgentLifecycle()
        .transition(AgentLifecycleStatus.READY)
        .transition(AgentLifecycleStatus.ACTIVE)
        .transition(AgentLifecycleStatus.DISABLED)
    )
    assert disabled.transition(AgentLifecycleStatus.RETIRED).is_terminal


def test_transition_rejects_non_status():
    lifecycle = AgentLifecycle()
    with pytest.raises(AgentContractError):
        lifecycle.transition("active")  # type: ignore[arg-type]


def test_to_dict_serializes():
    from typing import cast

    lifecycle = AgentLifecycle().transition(AgentLifecycleStatus.READY)
    data = lifecycle.to_dict()
    assert data["status"] == "ready"
    assert data["version"] == 1
    history = cast(list[dict[str, str]], data["history"])
    assert history[0]["to_status"] == "ready"


def test_lifecycle_holds_no_execution_authority():
    lifecycle = AgentLifecycle(AgentLifecycleStatus.ACTIVE, 1, ())
    # Lifecycle state never exposes execution.
    assert not hasattr(lifecycle, "execute")
    assert not hasattr(lifecycle, "run")
    assert not hasattr(lifecycle, "authorize")


def test_can_transition_to_validates_type():
    lifecycle = AgentLifecycle()
    assert lifecycle.can_transition_to(AgentLifecycleStatus.READY)
    assert not lifecycle.can_transition_to("ready")  # type: ignore[arg-type]