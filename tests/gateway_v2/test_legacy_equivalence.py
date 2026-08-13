"""Legacy equivalence + adapter overhead (Sprint 1.0.6 §45/§65)."""

import time

from agent.gateway_v2.adapter import GatewayV2Adapter, V2Decision

from .conftest import ALL_FALSE, make_request, make_registry


class FakeLegacyHandler:
    """Records exactly how the legacy path would be invoked."""

    def __init__(self):
        self.calls = []

    def handle(self, request):
        self.calls.append((request.request_id, request.goal))
        return {"ok": True, "text": f"legacy:{request.goal}"}


def test_legacy_equivalence_same_handler_same_response():
    """§45 — with all flags false, the legacy handler is invoked with the
    SAME arguments and returns the SAME response as before the adapter."""
    handler = FakeLegacyHandler()
    request = make_request(goal="hello")

    # before-adapter behavior
    before = handler.handle(request)

    # adapter decides (all flags false → LEGACY) → legacy path unchanged
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    decision = adapter.decide(request)
    after = handler.handle(request)

    assert decision is V2Decision.LEGACY
    assert after == before
    # identical invocation arguments on both sides of the adapter
    assert handler.calls[0] == handler.calls[1] == (request.request_id, "hello")
    # the adapter itself never invoked the handler
    assert not adapter.telemetry.counts().get("gateway.v2.canary.started")


def test_legacy_path_opens_no_store():
    """§65 — a pure legacy decision must not open SQLite."""
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    assert adapter._factory.create_store() is None  # no store, no schema


def test_decision_overhead_sub_millisecond():
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    request = make_request()
    adapter.decide(request)  # warm-up
    start = time.perf_counter()
    for _ in range(1000):
        adapter.decide(request)
    elapsed = (time.perf_counter() - start) / 1000
    assert elapsed < 0.001, f"decision too slow: {elapsed * 1000:.3f} ms"


def test_gateway_import_unaffected():
    """The hook must not break gateway import (lazy import inside hook)."""
    import importlib

    mod = importlib.import_module("gateway.run")
    assert hasattr(mod, "start_gateway")


def test_decide_event_never_raises():
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    assert adapter.decide_event(None) is V2Decision.LEGACY
    assert adapter.decide_event(object()) is V2Decision.LEGACY
