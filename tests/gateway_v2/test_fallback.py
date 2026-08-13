"""Fallback safety tests (Sprint 1.0.6 §30, MUST-HAVE 9/10/11)."""

from agent.execution.events import TOOL_COMPLETED, TOOL_STARTED
from agent.gateway_v2.adapter import GatewayV2Adapter
from agent.persistence import SQLiteExecutionStore
from agent.runtime.events import RuntimeEvent

from .conftest import ALL_FALSE, make_request, make_registry


def _store_with_event(tmp_path, event_type):
    store = SQLiteExecutionStore(str(tmp_path / "f.db"))
    from agent.runtime.models import AgentRun
    from agent.runtime.states import RunStatus
    from datetime import datetime, timezone

    run = AgentRun(id="run-1", task_type="t", status=RunStatus.RUNNING,
                   model_profile="BALANCED",
                   created_at=datetime.now(timezone.utc))
    store.save_run(run)
    store.append_event(RuntimeEvent(event_type=event_type, run_id="run-1",
                                    timestamp=datetime.now(timezone.utc),
                                    payload={"step": "s1"}))
    return store


def test_fallback_allowed_before_any_run():
    """§30 Case A — no AgentRun created → legacy fallback allowed."""
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    allowed, reason = adapter.can_fallback(run_id=None)
    assert allowed is True
    assert "no_v2_run_created" in reason
    assert adapter.legacy_fallback(run_id=None) is True


def test_fallback_allowed_with_zero_tools(tmp_path):
    """§30 Case B — run exists, ZERO TOOL_STARTED → fallback allowed."""
    store = SQLiteExecutionStore(str(tmp_path / "f.db"))
    from agent.runtime.models import AgentRun
    from agent.runtime.states import RunStatus
    from datetime import datetime, timezone

    store.save_run(AgentRun(id="run-1", task_type="t", status=RunStatus.PLANNING,
                            model_profile="BALANCED",
                            created_at=datetime.now(timezone.utc)))
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    allowed, reason = adapter.can_fallback("run-1", store)
    assert allowed is True
    assert "zero_tools_started" in reason
    store.close()


def test_fallback_forbidden_after_tool_started(tmp_path):
    """§30 Case C + MUST-HAVE 9 — TOOL_STARTED → fallback FORBIDDEN."""
    store = _store_with_event(tmp_path, TOOL_STARTED)
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    allowed, reason = adapter.can_fallback("run-1", store)
    assert allowed is False
    assert "v2_side_effect_possible" in reason
    assert adapter.legacy_fallback("run-1", store) is False
    store.close()


def test_fallback_forbidden_after_tool_completed(tmp_path):
    """§30 Case D — TOOL_COMPLETED → fallback FORBIDDEN (no duplicates)."""
    store = _store_with_event(tmp_path, TOOL_COMPLETED)
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    assert adapter.can_fallback("run-1", store)[0] is False
    store.close()


def test_exactly_one_response_contract():
    """§31 + MUST-HAVE 11 — shadow → legacy response only; canary → V2 only."""
    from agent.gateway_v2.adapter import V2Decision

    reg = make_registry()
    shadow_adapter = GatewayV2Adapter(flags=ALL_FALSE, registry=reg)
    # all-false: the only allowed outcome is LEGACY (one legacy response)
    assert shadow_adapter.decide(make_request()) is V2Decision.LEGACY
    # a canary run produces exactly one mapped response dict
    from .conftest import CANARY_ON
    from agent.gateway_v2.canary import V2CanaryPolicy

    policy = V2CanaryPolicy(allowed_users=["alice"], registry=reg)
    canary = GatewayV2Adapter(flags=CANARY_ON, registry=reg, canary_policy=policy)
    response = canary.run_canary(make_request(),
                                 step_specs=[{"name": "s1", "tool": "search"}])
    assert response["request_id"] == "req-1"
    assert len([k for k in response if k == "request_id"]) == 1


def test_fallback_telemetry_recorded():
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    adapter.legacy_fallback(run_id=None)
    counts = adapter.telemetry.counts()
    assert counts.get("gateway.v2.fallback.legacy") == 1
