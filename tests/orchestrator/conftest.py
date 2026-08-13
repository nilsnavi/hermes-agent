"""Shared fixtures for orchestrator tests (Sprint 1.0.5).

Fake tools + temporary SQLite only — no production state, no real tools.
"""

from datetime import datetime, timedelta, timezone

import pytest

from agent.execution.registry import SideEffectClass, ToolMetadata, ToolRegistry
from agent.persistence import SQLiteExecutionStore

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    """Injectable clock — advance() for deterministic time-budget tests."""

    def __init__(self, start: datetime = T0) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(tmp_path):
    s = SQLiteExecutionStore(str(tmp_path / "state.db"))
    yield s
    s.close()


def _make_registry(handlers=None):
    reg = ToolRegistry()
    reg.register("search", lambda a, c: {"hits": 1},
                 metadata=ToolMetadata(idempotent=True,
                                       side_effect_class=SideEffectClass.READ_ONLY))
    reg.register("fetch", lambda a, c: {"rows": 2},
                 metadata=ToolMetadata(idempotent=True,
                                       side_effect_class=SideEffectClass.READ_ONLY))
    reg.register("save_draft", lambda a, c: {"draft_id": "d-1"},
                 metadata=ToolMetadata(side_effect_class=SideEffectClass.REVERSIBLE_WRITE))
    reg.register("delete", lambda a, c: {"deleted": True},
                 metadata=ToolMetadata(side_effect_class=SideEffectClass.IRREVERSIBLE_WRITE))
    reg.register("publish", lambda a, c: {"published": True},
                 metadata=ToolMetadata(requires_approval=True,
                                       side_effect_class=SideEffectClass.IRREVERSIBLE_WRITE))
    for name, handler in (handlers or {}).items():
        if isinstance(handler, tuple):
            handler, metadata = handler
        else:
            metadata = None
        reg.register(name, handler, metadata=metadata)
    return reg


@pytest.fixture
def registry():
    return _make_registry()


def make_orchestrator(store, registry, clock):
    from agent.orchestrator import RuntimeOrchestrator

    return RuntimeOrchestrator(store, registry, clock=clock)


def spec(*tools, approval=None):
    """Build step specs: spec("search", "save_draft")."""
    specs = []
    for i, tool in enumerate(tools, start=1):
        raw = {"name": f"step-{i}", "tool": tool}
        if approval is not None:
            raw["requires_approval"] = approval
        specs.append(raw)
    return specs
