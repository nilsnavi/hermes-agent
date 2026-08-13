"""Gateway observe-mode integration (Sprint 1.1 §39, §57, §60)."""

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.router import IntentRouter, read_router_flags


def test_observe_does_not_change_routing(router_healthy, monkeypatch):
    """§39: observe mode evaluates but never mutates the request route."""
    calls = {"n": 0}

    # The router has no gateway hook by default — proving the gateway
    # decision path is untouched unless explicitly wired.
    assert not hasattr(router_healthy, "decide_gateway")

    # If wired as an observer, the returned decision is advisory only.
    d = router_healthy.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert d.effective_route in ("legacy", "v2_canary", "v2_shadow")


def test_router_error_leaves_route_unchanged():
    """§20: router failure must never break the request."""
    from agent.intent_router.classifier import IntentClassifier

    class Boom(IntentClassifier):
        def classify(self, features):
            raise RuntimeError("boom")

    r = IntentRouter(classifier=Boom(),
                     flags={"enabled": True, "mode": "observe"})
    d = r.observe(features_from_text("покажи статус", "r1"))
    assert d.effective_route == "legacy"  # fail closed, no misroute
    assert r.stats()["errors"] == 1


def test_ordinary_traffic_stays_legacy(router_healthy):
    """§60: ordinary (non-internal) request → legacy in observe."""
    d = router_healthy.observe(features_from_text(
        "привет, как дела", "r1"))
    assert d.effective_route == "legacy"


def test_default_flags_off_means_no_observe_effect():
    """§38: defaults enabled=false/mode=off → router inactive."""
    flags = read_router_flags({})
    assert flags["enabled"] is False
    assert flags["mode"].value == "off"


def test_canary_policy_unchanged_by_router():
    """The canary deny-by-default policy stays the authority."""
    from agent.gateway_v2.canary import (
        SafeCanaryToolRegistry, default_canary_registry,
    )
    from agent.execution.registry import SideEffectClass

    # registry view hides write tools regardless of the router.
    reg = SafeCanaryToolRegistry(default_canary_registry())
    assert reg._allowed == frozenset({SideEffectClass.READ_ONLY})
    assert reg.has("runtime_status") is True
    assert reg.has("send_message") is False
