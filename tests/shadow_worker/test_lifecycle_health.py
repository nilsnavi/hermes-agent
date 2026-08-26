"""Lifecycle + health tests (Phase 8.3 §13, §24)."""

from __future__ import annotations

import pytest

from agent.shadow_worker.config import WorkerConfig
from agent.shadow_worker.exceptions import WorkerConfigError
from agent.shadow_worker.health import WorkerHealth
from agent.shadow_worker.lifecycle import (
    WorkerLifecycle,
    WorkerLifecycleError,
    WorkerLifecycleState,
)


# -- lifecycle §13 -----------------------------------------------------------

def test_lifecycle_healthy_transitions():
    ls = WorkerLifecycleState()
    assert ls.state is WorkerLifecycle.STOPPED

    ls.transition(WorkerLifecycle.STARTING)
    ls.transition(WorkerLifecycle.HEALTHY)
    assert ls.is_healthy()
    ls.transition(WorkerLifecycle.STOPPING)
    ls.transition(WorkerLifecycle.STOPPED)
    assert ls.state is WorkerLifecycle.STOPPED


def test_lifecycle_rejects_invalid_transition():
    ls = WorkerLifecycleState(WorkerLifecycle.STOPPED)
    with pytest.raises(WorkerLifecycleError):
        ls.transition(WorkerLifecycle.HEALTHY)  # STOPPED -> HEALTHY is invalid


def test_lifecycle_downgrade_degrades():
    ls = WorkerLifecycleState()
    ls.transition(WorkerLifecycle.STARTING)
    ls.transition(WorkerLifecycle.HEALTHY)
    ls.transition(WorkerLifecycle.DEGRADED)
    assert not ls.is_healthy()
    ls.transition(WorkerLifecycle.HEALTHY)
    assert ls.is_healthy()


def test_lifecycle_informational_only_word():
    ls = WorkerLifecycleState(WorkerLifecycle.STARTING)
    assert ls.informational() == "starting"


# -- health faster / informational --------------------------------------------

def test_health_tracks_snapshot():
    h = WorkerHealth(WorkerLifecycle.STARTING)
    h.set_lifecycle(WorkerLifecycle.HEALTHY)
    h.bump_processed(3)
    snap = h.snapshot(queue_depth=2)
    assert snap.lifecycle is WorkerLifecycle.HEALTHY
    assert snap.envelopes_processed == 3
    assert snap.queue_depth == 2
    assert snap.is_ok()


def test_health_failed_is_not_ok():
    h = WorkerHealth()
    h.set_lifecycle(WorkerLifecycle.FAILED)
    assert not h.snapshot().is_ok()


def test_health_never_authority():
    # informational only: a HealthSnapshot carries no action to take
    h = WorkerHealth(WorkerLifecycle.DEGRADED)
    snap = h.snapshot()
    assert not snap.is_ok()
    # no mutation/activate/restart surface
    assert not hasattr(snap, "restart")
    assert not hasattr(snap, "signal")


# -- config §24 ---------------------------------------------------------------

def test_default_config_frozen_safe():
    c = WorkerConfig.from_mapping(None)
    assert c.enabled is False
    assert c.kill_switch_engaged is True
    assert c.sampling_percent == 0
    assert c.sampling_mode == "off"
    assert c.network_read_only is False
    assert c.memory_writes is False
    assert c.mutation_capabilities is False


def test_config_rejects_unknown_key():
    with pytest.raises(WorkerConfigError):
        WorkerConfig.from_mapping({"worker_enabled": True, "easter_egg": True})


def test_config_rejects_out_of_bounds():
    with pytest.raises(WorkerConfigError):
        WorkerConfig.from_mapping({"sampling_percent": 250})


def test_config_rejects_wrong_type():
    with pytest.raises(WorkerConfigError):
        WorkerConfig.from_mapping({"worker_enabled": "yes"})


def test_config_surfaces_enabled_when_cleared():
    c = WorkerConfig.from_mapping(
        {"worker_enabled": True, "shadow_kill_switch": False, "sampling_mode": "sample",
         "sampling_percent": 1})
    assert c.enabled is True
    assert c.kill_switch_engaged is False