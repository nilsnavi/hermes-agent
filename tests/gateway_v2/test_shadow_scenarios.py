"""Shadow scenario tests — S1..S6 (§27-32, §48).

Each controlled synthetic request must produce exactly one legacy
response (asserted via ShadowComparison.legacy_success), ZERO actual V2
tool calls, and the expected classification — never execution.
"""

from agent.gateway_v2.adapter import GatewayV2Adapter
from agent.gateway_v2.comparison import (
    INVALID_PLAN,
    NO_MISMATCH,
    SHADOW_EXCEPTION,
    WOULD_REQUIRE_APPROVAL,
    WOULD_REQUIRE_WRITE,
    ShadowComparison,
    build_comparison,
)
from agent.gateway_v2.flags import FeatureFlags
from agent.gateway_v2.shadow import default_shadow_registry

from .conftest import make_registry, make_request

SHADOW_ON = FeatureFlags(enabled=True, shadow=True)


def _shadow(request, step_specs, registry=None):
    adapter = GatewayV2Adapter(flags=SHADOW_ON,
                               registry=registry or default_shadow_registry())
    return adapter.shadow(request, step_specs=step_specs, timeout=1.0)


def _eligible(**kw):
    kw.setdefault("metadata", {"runtime_v2_shadow": True})
    kw.setdefault("allowed_tools", [])  # planner skips the allowlist check
    return make_request(**kw)


def test_s1_summarize_no_tools_legacy_success():
    """§27 — summarize-style request: legacy success, shadow plan valid,
    ZERO tool calls, one legacy response."""
    request = _eligible(goal="Summarize this supplied synthetic text")
    report = _shadow(request, step_specs=[{"name": "s1", "tool": "search"}])
    comp = build_comparison(request.request_id, report, legacy_success=True)
    assert report["plan_valid"] is True
    assert report["predicted_tool_calls"] == 1  # predicted, never executed
    assert comp.legacy_success is True
    assert comp.mismatch_flags == [NO_MISMATCH]
    assert comp.shadow_predicted_tools == 1


def test_s2_read_only_plan_never_executed():
    """§28 — planner predicts a read-only tool; ACTUAL tool calls = 0."""
    request = _eligible(goal="look up runtime status")
    report = _shadow(request, step_specs=[{"name": "s1", "tool": "runtime_status"}])
    comp = build_comparison(request.request_id, report)
    assert report["plan_valid"] is True
    assert report["predicted_tool_calls"] == 1
    assert report["would_require_write"] is False
    assert comp.mismatch_flags == [NO_MISMATCH]
    assert report["predicted_steps"] == 1


def test_s3_write_intent_only_classified():
    """§29 — write intent is CLASSIFIED, NEVER executed. The tool is
    known (REVERSIBLE_WRITE) → plan valid, but would_require_write."""
    request = _eligible(goal="create/update something on the server")
    report = _shadow(request, step_specs=[{"name": "s1", "tool": "send_message"}])
    comp = build_comparison(request.request_id, report)
    assert report["plan_valid"] is True
    assert report["would_require_write"] is True
    assert comp.mismatch_flags == [WOULD_REQUIRE_WRITE]
    # zero actual execution — nothing to assert beyond the guard tests


def test_s4_critical_risk_requires_approval_no_execution():
    """§30 — read-only task artificially risk=critical → approval required;
    no tool call, no approval UI, no write (matches 1.0.6 §48)."""
    request = _eligible(goal="read sensitive summary", risk_level="critical")
    report = _shadow(request, step_specs=[{"name": "s1", "tool": "search"}])
    comp = build_comparison(request.request_id, report)
    assert report["plan_valid"] is True
    assert report["would_require_approval"] is True
    assert report["would_require_write"] is False
    assert report["predicted_tool_calls"] == 0  # would pause at the gate
    assert comp.mismatch_flags == [WOULD_REQUIRE_APPROVAL]


def test_s4_deny_tools_denied():
    """§30 alt — risk policy DENY via metadata deny_tools → TOOL_NOT_ALLOWED."""
    request = _eligible(goal="touch forbidden", risk_level="low")
    request.metadata["deny_tools"] = ["delete_file"]
    report = _shadow(request, step_specs=[{"name": "s1", "tool": "delete_file"}])
    comp = build_comparison(request.request_id, report)
    assert report["plan_valid"] is True
    assert report["denied_steps"] == 1
    assert report["predicted_tool_calls"] == 0
    assert comp.mismatch_flags == ["TOOL_NOT_ALLOWED"]


def test_s5_invalid_plan_legacy_unaffected():
    """§31 — unknown tool → INVALID_PLAN; legacy stays the source of truth."""
    request = _eligible(goal="do the impossible")
    report = _shadow(request, step_specs=[{"name": "s1", "tool": "ghost_tool"}])
    comp = build_comparison(request.request_id, report)
    assert report["plan_valid"] is False
    assert report["predicted_tool_calls"] == 0
    assert any("unknown tool" in i for i in report["issues"])
    assert comp.mismatch_flags == [INVALID_PLAN]
    assert comp.legacy_success is True


def test_s5_no_steps_is_no_plan():
    """§31 alt — no step_specs → no plan → NO_PLAN (documented limitation:
    V2 shadow needs explicit step_specs, no autonomous planning)."""
    request = _eligible(goal="anything")
    report = _shadow(request, step_specs=[])
    comp = build_comparison(request.request_id, report)
    assert report["plan_valid"] is False
    assert comp.mismatch_flags == ["NO_PLAN"]


def test_s6_shadow_exception_isolated():
    """§32 — an injected shadow failure is captured (shadow.failed), legacy
    still succeeds, no user-visible error, no retry."""

    class BoomRegistry:
        def has(self, name):
            return True

        def is_allowed(self, name):
            return True

        def names(self):
            return ["search"]

        def metadata(self, name):
            raise RuntimeError("injected boom")

        def validator(self, name):
            return None

    request = _eligible(goal="boom case")
    report = _shadow(request, step_specs=[{"name": "s1", "tool": "search"}],
                     registry=BoomRegistry())  # type: ignore[arg-type]
    comp = build_comparison(request.request_id, report)
    assert report["ok"] is False
    assert "shadow error" in report["reason"]
    assert comp.mismatch_flags == [SHADOW_EXCEPTION]
    assert comp.legacy_success is True  # legacy unaffected by shadow boom


def test_s6_shadow_timeout_isolated():
    """§32 alt — timeout is SHADOW_EXCEPTION, legacy still succeeds."""

    class SlowRegistry:
        def has(self, name):
            return True

        def is_allowed(self, name):
            return True

        def names(self):
            return ["search"]

        def metadata(self, name):
            import time

            time.sleep(5)

        def validator(self, name):
            return None

    request = _eligible(goal="slow case")
    adapter = GatewayV2Adapter(flags=SHADOW_ON,
                               registry=SlowRegistry())  # type: ignore[arg-type]
    report = adapter.shadow(request, step_specs=[{"name": "s1", "tool": "search"}],
                            timeout=0.3)
    comp = build_comparison(request.request_id, report)
    assert report["timed_out"] is True
    assert comp.mismatch_flags == [SHADOW_EXCEPTION]
    assert comp.legacy_success is True
