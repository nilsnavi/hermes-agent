"""Memory lifecycle state machine tests."""

import pytest

from agent.platform_memory.memory_lifecycle import (
    InvalidMemoryTransition,
    MemoryLifecycle,
    MemoryLifecycleStatus,
)


def test_new_lifecycle_starts_created():
    lifecycle = MemoryLifecycle()
    assert lifecycle.status is MemoryLifecycleStatus.CREATED
    assert lifecycle.version == 0


def test_legal_active_transition():
    lifecycle = MemoryLifecycle().transition(MemoryLifecycleStatus.ACTIVE)
    assert lifecycle.status is MemoryLifecycleStatus.ACTIVE
    assert lifecycle.version == 1


def test_illegal_skip_rejected():
    with pytest.raises(InvalidMemoryTransition):
        MemoryLifecycle().transition(MemoryLifecycleStatus.CONSOLIDATED)


def test_forgotten_is_terminal_immutable():
    forgotten = (
        MemoryLifecycle()
        .transition(MemoryLifecycleStatus.ACTIVE)
        .transition(MemoryLifecycleStatus.FORGOTTEN)
    )
    assert forgotten.is_terminal
    with pytest.raises(InvalidMemoryTransition):
        forgotten.transition(MemoryLifecycleStatus.ACTIVE)


def test_retired_is_terminal_immutable():
    retired = MemoryLifecycle().transition(MemoryLifecycleStatus.RETIRED)
    assert retired.is_terminal
    with pytest.raises(InvalidMemoryTransition):
        retired.transition(MemoryLifecycleStatus.CREATED)


def test_consolidation_path():
    consolidated = (
        MemoryLifecycle()
        .transition(MemoryLifecycleStatus.ACTIVE)
        .transition(MemoryLifecycleStatus.CONSOLIDATED)
    )
    assert consolidated.status is MemoryLifecycleStatus.CONSOLIDATED
    # consolidated can still be forgotten, not re-activated
    assert consolidated.can_transition_to(MemoryLifecycleStatus.ACTIVE) is False
    assert consolidated.can_transition_to(MemoryLifecycleStatus.FORGOTTEN) is True


def test_lifecycle_grants_no_authority():
    lifecycle = MemoryLifecycle()
    assert not hasattr(lifecycle, "grant")
    assert not hasattr(lifecycle, "approve_execution")
    assert not hasattr(lifecycle, "bypass")