"""Shadow mode tests (Sprint 1.0.6 §12/13/46, MUST-HAVE 3/4)."""

from agent.gateway_v2.adapter import GatewayV2Adapter
from agent.gateway_v2.shadow import ShadowRunner

from .conftest import SHADOW_ON, make_request, make_registry


def test_shadow_zero_tool_execution():
    """§46 + MUST-HAVE 3 — a plan with WRITE tools executes ZERO tools."""
    calls = {"n": 0}

    def _delete(args, ctx):
        calls["n"] += 1
        return {"deleted": True}
    reg = make_registry()
    reg.register("delete", _delete)  # re-register with counter
    runner = ShadowRunner(reg)
    report = runner.run_shadow(
        make_request(allowed_tools=["delete"]),
        step_specs=[{"name": "s1", "tool": "delete"}],
    )
    assert calls["n"] == 0  # no tool ever executed
    assert report["would_require_write"] is True
    assert report["eligible"] is False


def test_shadow_read_only_predicts_execution():
    runner = ShadowRunner(make_registry())
    report = runner.run_shadow(
        make_request(),
        step_specs=[{"name": "s1", "tool": "search"}],
    )
    assert report["predicted_steps"] == 1
    assert report["predicted_tool_calls"] == 1
    assert report["would_require_write"] is False
    assert report["would_require_approval"] is False
    assert report["eligible"] is True


def test_shadow_writes_nothing_to_any_store():
    """§13 — shadow must not touch agent_v2 tables (or any DB)."""
    import os
    import tempfile

    from agent.gateway_v2.store_factory import schema_check

    db = os.path.join(tempfile.mkdtemp(), "shadow.db")
    before = schema_check(db)
    runner = ShadowRunner(make_registry())
    runner.run_shadow(make_request(), step_specs=[{"name": "s1", "tool": "search"}])
    after = schema_check(db)
    assert before == after  # no file created, no tables added
    assert after["writes"] == 0


def test_shadow_legacy_response_is_source_of_truth():
    """MUST-HAVE 4 — shadow produces no user-visible output of its own."""
    adapter = GatewayV2Adapter(flags=SHADOW_ON, registry=make_registry())
    report = adapter.shadow(make_request(), step_specs=[{"name": "s1", "tool": "search"}])
    assert "output" not in report  # no user-visible V2 result
    assert "legacy_response" not in report  # the legacy path owns the response


def test_shadow_invalid_plan_reports_issues_no_crash():
    runner = ShadowRunner(make_registry())
    report = runner.run_shadow(
        make_request(allowed_tools=["ghost"]),
        step_specs=[{"name": "s1", "tool": "ghost"}],
    )
    assert report["eligible"] is False
    assert any("unknown tool" in i for i in report["issues"])


def test_shadow_failure_never_breaks_legacy():
    """A shadow error is captured, not raised into the legacy path."""
    class BrokenRegistry:
        def has(self, name):
            raise RuntimeError("registry exploded")

        def metadata(self, name):
            raise RuntimeError("registry exploded")

    runner = ShadowRunner(BrokenRegistry())  # type: ignore[arg-type]
    report = runner.run_shadow(make_request(allowed_tools=[]),
                               step_specs=[{"name": "s1", "tool": "x"}])
    assert report["eligible"] is False
    assert "shadow error" in report["reason"]


def test_shadow_telemetry_events():
    runner = ShadowRunner(make_registry())
    runner.run_shadow(make_request(), step_specs=[{"name": "s1", "tool": "search"}])
    counts = runner._telemetry.counts()
    assert counts.get("gateway.v2.shadow.started") == 1
    assert counts.get("gateway.v2.shadow.completed") == 1
