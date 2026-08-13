"""Shadow execution guard tests (Sprint 1.0.6.1 §20/§21).

Tool handlers must NEVER run in shadow mode. NoExecuteToolRegistry makes
handler access impossible by construction, and even the diagnostic
registry's own handlers raise ShadowToolExecutionForbidden if invoked.
"""

import pytest

from agent.execution.registry import SideEffectClass
from agent.gateway_v2.exceptions import ShadowToolExecutionForbidden
from agent.gateway_v2.shadow import (
    NoExecuteToolRegistry,
    ShadowRunner,
    default_shadow_registry,
)

from .conftest import make_registry, make_request


def test_no_execute_registry_get_raises():
    reg = NoExecuteToolRegistry(make_registry())
    assert reg.has("search") is True
    assert reg.metadata("search").side_effect_class is SideEffectClass.READ_ONLY
    with pytest.raises(ShadowToolExecutionForbidden):
        reg.get("search")
    with pytest.raises(ShadowToolExecutionForbidden):
        reg.execute("search", {}, {})


def test_no_execute_registry_unknown_tool_has_false():
    reg = NoExecuteToolRegistry(make_registry())
    assert reg.has("ghost_tool") is False


def test_diagnostic_handlers_raise_if_invoked():
    reg = default_shadow_registry()
    assert reg.has("search") and reg.has("delete_file") and reg.has("send_message")
    assert reg.metadata("search").side_effect_class is SideEffectClass.READ_ONLY
    assert reg.metadata("delete_file").side_effect_class \
        is SideEffectClass.IRREVERSIBLE_WRITE
    assert reg.metadata("send_message").side_effect_class \
        is SideEffectClass.REVERSIBLE_WRITE
    with pytest.raises(ShadowToolExecutionForbidden):
        reg.get("search")({}, {})
    with pytest.raises(ShadowToolExecutionForbidden):
        reg.get("delete_file")({}, {})


def test_shadow_run_invokes_zero_handlers():
    """MUST-HAVE: shadow executes ZERO tool handlers — counter stays 0."""
    calls = {"n": 0}

    def counting_handler(*args, **kwargs):
        calls["n"] += 1
        return {"ok": True}

    reg = make_registry()
    # re-register with a counting handler to prove no invocation
    reg.register("search", counting_handler,
                 metadata=reg.metadata("search"))
    runner = ShadowRunner(reg)
    report = runner.run_shadow(
        make_request(),
        step_specs=[{"name": "s1", "tool": "search"}],
    )
    assert report["ok"] is True
    assert calls["n"] == 0  # §9: tool calls MUST = 0


def test_shadow_runner_wraps_registry_with_no_execute():
    """The runner must hand the ORCHESTRATOR a NoExecute view, so even a
    buggy dry_run path cannot reach a handler."""
    runner = ShadowRunner(make_registry())
    assert isinstance(runner._registry, NoExecuteToolRegistry)
    with pytest.raises(ShadowToolExecutionForbidden):
        runner._registry.get("search")


def test_shadow_timeout_reports_failed_without_raising():
    """§19 — a hung dry_run must time out, not block or raise."""

    class SlowRegistry:
        def has(self, name):
            return True

        def is_allowed(self, name):
            return True

        def names(self):
            return ["search"]

        def metadata(self, name):
            import time

            time.sleep(5)  # simulate a pathological planner/registry
            from agent.execution.registry import ToolMetadata
            return ToolMetadata()

        def validator(self, name):
            return None

    runner = ShadowRunner(SlowRegistry())  # type: ignore[arg-type]
    report = runner.run_shadow(
        make_request(),
        step_specs=[{"name": "s1", "tool": "search"}],
        timeout=0.3,
    )
    assert report["timed_out"] is True
    assert report["ok"] is False
    assert "timed out" in report["reason"]
