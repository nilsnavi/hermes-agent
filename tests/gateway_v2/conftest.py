"""Shared fixtures for gateway_v2 tests (Sprint 1.0.6)."""

from datetime import datetime, timedelta, timezone

import pytest

from agent.execution.registry import SideEffectClass, ToolMetadata, ToolRegistry
from agent.gateway_v2.flags import FeatureFlags
from agent.gateway_v2.context_builder import GatewayRequest

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


class FakeClock:
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
    from agent.persistence import SQLiteExecutionStore

    s = SQLiteExecutionStore(str(tmp_path / "state.db"))
    yield s
    s.close()


def make_registry():
    reg = ToolRegistry()
    reg.register("search", lambda a, c: {"hits": 1},
                 metadata=ToolMetadata(idempotent=True,
                                       side_effect_class=SideEffectClass.READ_ONLY))
    reg.register("runtime_status", lambda a, c: {"gateway": "active"},
                 metadata=ToolMetadata(idempotent=True,
                                       side_effect_class=SideEffectClass.READ_ONLY))
    reg.register("delete", lambda a, c: {"deleted": True},
                 metadata=ToolMetadata(side_effect_class=SideEffectClass.IRREVERSIBLE_WRITE))
    reg.register("save_draft", lambda a, c: {"draft_id": "d"},
                 metadata=ToolMetadata(side_effect_class=SideEffectClass.REVERSIBLE_WRITE))
    return reg


@pytest.fixture
def registry():
    return make_registry()


ALL_FALSE = FeatureFlags()
SHADOW_ON = FeatureFlags(enabled=True, shadow=True)
CANARY_ON = FeatureFlags(enabled=True, persistence=True, canary=True)


def make_request(**kw):
    defaults = dict(request_id="req-1", user_id="alice", session_id="sess-1",
                    request_type="chat", goal="do something", allowed_tools=["search"],
                    metadata={"runtime_v2": True})
    defaults.update(kw)
    return GatewayRequest(**defaults)
