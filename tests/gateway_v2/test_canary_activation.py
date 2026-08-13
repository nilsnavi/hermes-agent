"""Canary activation tests (Sprint 1.0.6.2 §8/§11/§14/§20/§21-22/§23).

- opt-in key: runtime_v2_canary (runtime_v2 kept as a 1.0.6 alias);
- precedence: CANARY wins over SHADOW for an eligible canary request;
- SafeCanaryToolRegistry + default_canary_registry: write tools are
  IMPOSSIBLE by construction; real READ_ONLY tools execute;
- canary_event: exactly-one-response contract + fallback rules (§21-22).
"""

import pytest

from agent.execution.registry import SideEffectClass
from agent.gateway_v2.adapter import GatewayV2Adapter, V2Decision
from agent.gateway_v2.canary import (
    V2CanaryPolicy,
    default_canary_registry,
)
from agent.gateway_v2.flags import FeatureFlags

from .conftest import make_registry, make_request

CANARY_ON = FeatureFlags(enabled=True, persistence=True, canary=True)
BOTH_ON = FeatureFlags(enabled=True, persistence=True, shadow=True, canary=True)


def _adapter(**policy_kw):
    reg = make_registry()
    policy = V2CanaryPolicy(allowed_users=["alice"], registry=reg, **policy_kw)
    return GatewayV2Adapter(flags=CANARY_ON, registry=reg, canary_policy=policy), reg


# ── opt-in key (§8) ───────────────────────────────────────────────────────


def test_canary_optin_runtime_v2_canary():
    adapter, _ = _adapter()
    request = make_request(metadata={"runtime_v2_canary": True})
    assert adapter.decide(request) is V2Decision.V2_CANARY


def test_canary_optin_runtime_v2_alias_still_works():
    adapter, _ = _adapter()
    request = make_request(metadata={"runtime_v2": True})  # 1.0.6 alias
    assert adapter.decide(request) is V2Decision.V2_CANARY


def test_canary_optin_strict_and_deny_by_default():
    adapter, _ = _adapter()
    assert adapter.decide(make_request(metadata={})) is V2Decision.LEGACY
    assert adapter.decide(make_request(metadata={"runtime_v2_canary": "0"})) \
        is V2Decision.LEGACY
    assert adapter.decide(make_request(metadata={"runtime_v2_canary": "banana"})) \
        is V2Decision.LEGACY


def test_canary_requires_all_allowlists():
    adapter, _ = _adapter(allowed_sessions=["sess-1"])
    assert adapter.decide(make_request(metadata={"runtime_v2_canary": True})) \
        is V2Decision.V2_CANARY
    assert adapter.decide(make_request(
        session_id="other", metadata={"runtime_v2_canary": True})) \
        is V2Decision.LEGACY


# ── precedence (§20) ──────────────────────────────────────────────────────


def test_canary_wins_over_shadow():
    reg = make_registry()
    policy = V2CanaryPolicy(allowed_users=["alice"], registry=reg)
    adapter = GatewayV2Adapter(flags=BOTH_ON, registry=reg, canary_policy=policy)
    request = make_request(metadata={"runtime_v2_canary": True,
                                     "runtime_v2_shadow": True})
    assert adapter.decide(request) is V2Decision.V2_CANARY
    # shadow-eligible but NOT canary-eligible → SHADOW
    shadow_only = make_request(metadata={"runtime_v2_shadow": True})
    assert adapter.decide(shadow_only) is V2Decision.SHADOW


# ── registry (§11/§14) ────────────────────────────────────────────────────


def test_default_canary_registry_all_read_only():
    reg = default_canary_registry()
    for name in reg.names():
        assert reg.metadata(name).side_effect_class is SideEffectClass.READ_ONLY
    assert set(reg.names()) == {"runtime_status", "canary_ping"}


def test_default_canary_handlers_real_and_local():
    reg = default_canary_registry()
    out1 = reg.get("canary_ping")({}, {})
    assert out1["ok"] is True and "ts" in out1
    out2 = reg.get("runtime_status")({}, {})
    assert isinstance(out2, dict) and out2  # real local read (or fallback)


def test_write_tools_impossible_in_canary():
    """§14 — even a write tool in the base registry is invisible through
    SafeCanaryToolRegistry → INVALID_PLAN → zero execution."""
    from agent.gateway_v2.canary import SafeCanaryToolRegistry

    reg = make_registry()  # has delete (IRREVERSIBLE_WRITE)
    safe = SafeCanaryToolRegistry(reg)
    assert safe.has("search") is True
    assert safe.has("delete") is False
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=reg,
                               canary_policy=V2CanaryPolicy(
                                   allowed_users=["alice"], registry=reg))
    request = make_request(allowed_tools=[], metadata={"runtime_v2_canary": True})
    response = adapter.run_canary(
        request, step_specs=[{"name": "s1", "tool": "delete"}],
        db_path=None, allow_production=False,
    )
    assert response["ok"] is False  # invalid plan / zero execution
    assert response["code"] in ("V2_EXECUTION_FAILED", "V2_INTERNAL_ERROR")


# ── canary_event (§19/§21-22) ─────────────────────────────────────────────


class FakeEvent:
    def __init__(self, event_id="evt-1", text="status please", user_id="alice",
                 session_id="sess-1", metadata=None):
        self.id = event_id
        self.text = text
        self.user_id = user_id
        self.session_id = session_id
        self.metadata = dict(metadata or {})
        self.internal = False


def test_canary_event_ordinary_event_legacy_fallback_allowed(tmp_path):
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=make_registry(),
                               canary_policy=V2CanaryPolicy(
                                   allowed_users=["alice"],
                                   registry=make_registry()))
    result = adapter.canary_event(FakeEvent(text="ordinary"),
                                  db_path=str(tmp_path / "c.db"),
                                  allow_production=True)
    assert result["ok"] is False
    assert result["code"] == "V2_NOT_ELIGIBLE"
    assert result["fallback_allowed"] is True  # no side effect → legacy OK


def test_canary_event_eligible_runs_and_single_response(tmp_path):
    """§19/§23 — an eligible event drives the canary path durably.

    The live hook passes NO step_specs (V2 has no autonomous planning),
    so the deterministic planner reports NO_PLAN: the run is persisted,
    zero tools execute, fallback to legacy stays ALLOWED (no side
    effect), and the hook receives a controlled dict — exactly one
    response contract holds (output_text absent, never a legacy+V2
    double send)."""
    from agent.gateway_v2.canary import default_canary_registry

    reg = default_canary_registry()
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=reg,
                               canary_policy=V2CanaryPolicy(
                                   allowed_users=["alice"], registry=reg))
    event = FakeEvent(text="status please",
                      metadata={"runtime_v2_canary": True})
    result = adapter.canary_event(event, db_path=str(tmp_path / "c.db"),
                                  allow_production=True)
    assert result["ok"] is False  # NO_PLAN without step_specs (bounded)
    assert result["code"] == "V2_EXECUTION_FAILED"
    assert result["fallback_allowed"] is True  # zero tools started
    assert "output_text" not in result  # exactly-one: no premature output
    # run persisted durably (agent_v2_runs row exists)
    import sqlite3

    con = sqlite3.connect(str(tmp_path / "c.db"))
    runs = con.execute("SELECT COUNT(*) FROM agent_v2_runs").fetchone()[0]
    con.close()
    assert runs == 1
    # the EXECUTION path (with step_specs) is covered by run_canary +
    # the CLI canary-suite C1-C7c batch.


def test_canary_failure_before_tool_allows_fallback(tmp_path):
    class BoomRegistry:
        def has(self, name):
            return True

        def is_allowed(self, name):
            return True

        def names(self):
            return ["runtime_status"]

        def metadata(self, name):
            raise RuntimeError("boom")

        def validator(self, name):
            return None

    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=BoomRegistry(),  # type: ignore[arg-type]
                               canary_policy=V2CanaryPolicy(
                                   allowed_users=["alice"],
                                   registry=make_registry()))
    event = FakeEvent(text="status", metadata={"runtime_v2_canary": True})
    result = adapter.canary_event(event, db_path=str(tmp_path / "c.db"),
                                  allow_production=True)
    assert result["ok"] is False
    assert result["code"] == "V2_EXECUTION_FAILED"
    assert result["fallback_allowed"] is True  # zero tools started
    # §22 fallback-after-TOOL_STARTED is forbidden — covered by
    # test_fallback.py::test_fallback_forbidden_after_tool_started.
