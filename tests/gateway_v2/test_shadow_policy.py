"""Shadow eligibility policy tests (Sprint 1.0.6.1 §7/§33/§50).

Deny-by-default: ordinary requests are NEVER shadow-eligible; only an
explicit runtime_v2_shadow opt-in (strict true/1/yes) can route to
SHADOW, and only when allowlists (if any) are satisfied.
"""

from agent.gateway_v2.adapter import GatewayV2Adapter, V2Decision
from agent.gateway_v2.flags import FeatureFlags
from agent.gateway_v2.shadow_policy import V2ShadowPolicy

from .conftest import make_registry, make_request

SHADOW_ON = FeatureFlags(enabled=True, shadow=True)


def _adapter(**policy_kw):
    return GatewayV2Adapter(flags=SHADOW_ON, registry=make_registry(),
                            shadow_policy=V2ShadowPolicy(**policy_kw))


def test_ordinary_request_never_shadowed():
    """MUST-HAVE (1.0.6.1): ordinary unmarked traffic stays LEGACY."""
    adapter = _adapter()
    assert adapter.decide(make_request(metadata={})) is V2Decision.LEGACY
    assert adapter.decide(make_request()) is V2Decision.LEGACY  # runtime_v2 only


def test_explicit_optin_routes_shadow():
    adapter = _adapter()
    request = make_request(metadata={"runtime_v2_shadow": True})
    assert adapter.decide(request) is V2Decision.SHADOW


def test_optin_strict_parsing():
    """Only true/1/yes (case-insensitive) counts; anything else → LEGACY."""
    adapter = _adapter()
    for value in ("true", "TRUE", "1", "yes", "Yes"):
        assert adapter.decide(
            make_request(metadata={"runtime_v2_shadow": value})
        ) is V2Decision.SHADOW
    for value in ("0", "false", "no", "banana", "", None, 2, []):
        assert adapter.decide(
            make_request(metadata={"runtime_v2_shadow": value})
        ) is V2Decision.LEGACY


def test_shadow_flag_off_never_shadowed_even_with_optin():
    adapter = GatewayV2Adapter(flags=FeatureFlags(), registry=make_registry(),
                               shadow_policy=V2ShadowPolicy())
    assert adapter.decide(
        make_request(metadata={"runtime_v2_shadow": True})
    ) is V2Decision.LEGACY


def test_allowlist_user_enforced():
    adapter = _adapter(allowed_users=["alice"])
    assert adapter.decide(
        make_request(metadata={"runtime_v2_shadow": True})
    ) is V2Decision.SHADOW
    assert adapter.decide(
        make_request(user_id="mallory", metadata={"runtime_v2_shadow": True})
    ) is V2Decision.LEGACY


def test_allowlist_session_enforced():
    adapter = _adapter(allowed_sessions=["sess-1"])
    assert adapter.decide(
        make_request(metadata={"runtime_v2_shadow": True})
    ) is V2Decision.SHADOW
    assert adapter.decide(
        make_request(session_id="other", metadata={"runtime_v2_shadow": True})
    ) is V2Decision.LEGACY


def test_no_percentage_or_random_rollout():
    """Decision is a pure function of the request — same request, same
    decision, 1000× (deterministic, no hash % / every-Nth sampling)."""
    adapter = _adapter()
    eligible = make_request(metadata={"runtime_v2_shadow": True})
    ordinary = make_request(metadata={})
    assert {adapter.decide(eligible) for _ in range(1000)} == {V2Decision.SHADOW}
    assert {adapter.decide(ordinary) for _ in range(1000)} == {V2Decision.LEGACY}


def test_policy_summary_deny_by_default():
    summary = V2ShadowPolicy().summary()
    assert summary["deny_by_default"] is True
    assert summary["allowed_users"] == []
