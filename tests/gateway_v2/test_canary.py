"""Canary mode tests (Sprint 1.0.6 §14-15/47/48, MUST-HAVE 5-8)."""

from agent.execution.registry import SideEffectClass, ToolMetadata
from agent.gateway_v2.adapter import GatewayV2Adapter
from agent.gateway_v2.canary import SafeCanaryToolRegistry, V2CanaryPolicy

from .conftest import CANARY_ON, make_request, make_registry


def _canary_adapter(reg, allowed_users=("alice",)):
    policy = V2CanaryPolicy(allowed_users=list(allowed_users), registry=reg)
    return GatewayV2Adapter(flags=CANARY_ON, registry=reg, canary_policy=policy)


def test_canary_deny_by_default():
    """MUST-HAVE 5 — empty allowlist denies everything."""
    reg = make_registry()
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=reg,
                               canary_policy=V2CanaryPolicy(registry=reg))
    response = adapter.run_canary(make_request(),
                                  step_specs=[{"name": "s1", "tool": "search"}])
    assert response["ok"] is False
    assert response["code"] == "V2_NOT_ELIGIBLE"


def test_read_only_canary_completes():
    """MUST-HAVE 6 + §47 — read-only E2E completes with safe output."""
    reg = make_registry()
    adapter = _canary_adapter(reg)
    response = adapter.run_canary(
        make_request(allowed_tools=["search", "runtime_status"]),
        step_specs=[{"name": "s1", "tool": "search"},
                    {"name": "s2", "tool": "runtime_status"}],
    )
    assert response["ok"] is True
    assert response["code"] == "V2_OK"
    assert response["output"] == {
        "step-1": {"hits": 1},
        "step-2": {"gateway": "active"},
    }
    assert "run_id" not in response  # internal id never exposed


def test_write_canary_denied():
    """MUST-HAVE 7 — a write tool is impossible in canary (invisible)."""
    calls = {"delete": 0}

    def _delete(args, ctx):
        calls["delete"] += 1
        return {"deleted": True}
    reg = make_registry()
    reg.register("delete", _delete)
    adapter = _canary_adapter(reg)
    response = adapter.run_canary(
        make_request(allowed_tools=["delete"]),
        step_specs=[{"name": "s1", "tool": "delete"}],
    )
    assert response["ok"] is False
    assert calls["delete"] == 0  # write tool NEVER executed
    assert "V2_" in response["code"]


def test_critical_risk_pauses_canary():
    """MUST-HAVE 8 + §48 — critical risk → approval pause, no tool, no fallback."""
    reg = make_registry()
    adapter = _canary_adapter(reg)
    response = adapter.run_canary(
        make_request(risk_level="critical"),
        step_specs=[{"name": "s1", "tool": "search"}],
    )
    assert response["ok"] is False
    assert response["code"] == "V2_APPROVAL_REQUIRED"
    assert response["output"] is None


def test_safe_registry_hides_write_tools():
    reg = make_registry()
    safe = SafeCanaryToolRegistry(reg)
    assert safe.has("search") is True
    assert safe.has("delete") is False
    assert safe.has("save_draft") is False
    assert safe.names() == ["runtime_status", "search"]


def test_safe_registry_unknown_tool_invisible():
    reg = make_registry()
    safe = SafeCanaryToolRegistry(reg)
    assert safe.has("ghost") is False


def test_canary_uses_temp_db_not_production():
    import os

    reg = make_registry()
    adapter = _canary_adapter(reg)
    store = adapter._factory.create_store()
    assert store is not None
    path = store._path
    assert "canary" in path and not path.endswith("state.db")
    store.close()


def test_canary_exactly_one_response():
    """§31 — canary returns exactly one mapped response."""
    reg = make_registry()
    adapter = _canary_adapter(reg)
    response = adapter.run_canary(make_request(),
                                  step_specs=[{"name": "s1", "tool": "search"}])
    assert isinstance(response, dict)
    assert "request_id" in response
    assert response["code"] in ("V2_OK", "V2_NOT_ELIGIBLE",
                                "V2_APPROVAL_REQUIRED", "V2_EXECUTION_FAILED",
                                "V2_INTERNAL_ERROR", "V2_NOT_ENABLED")
