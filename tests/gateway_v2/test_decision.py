"""Request decision tests (Sprint 1.0.6 §44, MUST-HAVE 1/2/5)."""

from agent.gateway_v2.adapter import GatewayV2Adapter, V2Decision
from agent.gateway_v2.canary import V2CanaryPolicy

from .conftest import ALL_FALSE, CANARY_ON, SHADOW_ON, make_request, make_registry


def test_all_flags_false_is_legacy():
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    assert adapter.decide(make_request()) is V2Decision.LEGACY


def test_shadow_flag_routes_shadow_only_when_eligible():
    """Sprint 1.0.6.1 §7/§33 — shadow is DENY-BY-DEFAULT: an ordinary
    request stays LEGACY even with ENABLED+SHADOW=true; only an explicit
    runtime_v2_shadow opt-in routes to SHADOW."""
    adapter = GatewayV2Adapter(flags=SHADOW_ON, registry=make_registry())
    # ordinary request (no shadow opt-in) → LEGACY
    assert adapter.decide(make_request(metadata={})) is V2Decision.LEGACY
    # explicit shadow opt-in → SHADOW
    eligible = make_request(metadata={"runtime_v2_shadow": True})
    assert adapter.decide(eligible) is V2Decision.SHADOW
    # strict opt-in parsing: "0"/garbage is NOT eligible
    assert adapter.decide(make_request(metadata={"runtime_v2_shadow": "0"})) \
        is V2Decision.LEGACY
    assert adapter.decide(make_request(metadata={"runtime_v2_shadow": "banana"})) \
        is V2Decision.LEGACY


def test_canary_non_eligible_falls_back_to_legacy():
    # deny-by-default: empty allowlist → not eligible
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=make_registry(),
                               canary_policy=V2CanaryPolicy(registry=make_registry()))
    assert adapter.decide(make_request()) is V2Decision.LEGACY


def test_canary_eligible_routes_v2():
    reg = make_registry()
    policy = V2CanaryPolicy(allowed_users=["alice"], registry=reg)
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=reg, canary_policy=policy)
    assert adapter.decide(make_request()) is V2Decision.V2_CANARY


def test_write_required_request_not_canary_eligible():
    reg = make_registry()
    policy = V2CanaryPolicy(allowed_users=["alice"], registry=reg)
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=reg, canary_policy=policy)
    request = make_request(allowed_tools=["delete"])  # IRREVERSIBLE_WRITE
    assert adapter.decide(request) is V2Decision.LEGACY


def test_unknown_user_is_legacy():
    reg = make_registry()
    policy = V2CanaryPolicy(allowed_users=["alice"], registry=reg)
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=reg, canary_policy=policy)
    request = make_request(user_id="mallory")
    assert adapter.decide(request) is V2Decision.LEGACY


def test_no_explicit_optin_is_legacy():
    reg = make_registry()
    policy = V2CanaryPolicy(allowed_users=["alice"], registry=reg)
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=reg, canary_policy=policy)
    request = make_request(metadata={})  # no runtime_v2=true
    assert adapter.decide(request) is V2Decision.LEGACY


def test_session_allowlist_enforced():
    reg = make_registry()
    policy = V2CanaryPolicy(allowed_users=["alice"], allowed_sessions=["sess-1"],
                            registry=reg)
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=reg, canary_policy=policy)
    assert adapter.decide(make_request()) is V2Decision.V2_CANARY
    assert adapter.decide(make_request(session_id="other")) is V2Decision.LEGACY


def test_decision_is_deterministic():
    reg = make_registry()
    policy = V2CanaryPolicy(allowed_users=["alice"], registry=reg)
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=reg, canary_policy=policy)
    results = {adapter.decide(make_request()) for _ in range(5)}
    assert results == {V2Decision.V2_CANARY}


def test_decision_records_telemetry_without_prompt():
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    adapter.decide(make_request(goal="secret prompt text"))
    events = adapter.telemetry.recent(1)
    assert events[0]["event"] == "gateway.v2.decision"
    assert "goal" not in events[0] and "secret" not in str(events[0])
