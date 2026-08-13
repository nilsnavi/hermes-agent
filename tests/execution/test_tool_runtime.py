"""ToolRuntime + ToolRegistry tests (Sprint 1.0.2)."""

import time

import pytest

from agent.execution.exceptions import ToolNotAllowed
from agent.execution.registry import ToolRegistry
from agent.execution.tool_runtime import (
    STATUS_FAILURE,
    STATUS_PERMISSION_DENIED,
    STATUS_SUCCESS,
    STATUS_TIMEOUT,
    ToolRuntime,
)


def _echo(args, ctx):
    return {"echo": args.get("q"), "ctx_run": ctx.get("run_id")}


def _boom(args, ctx):
    raise ValueError("boom")


def _slow(args, ctx):
    time.sleep(0.5)
    return {"done": True}


def _registry(handlers=None):
    reg = ToolRegistry()
    reg.register("echo", _echo)
    reg.register("boom", _boom)
    reg.register("slow", _slow)
    for name, (handler, validator) in (handlers or {}).items():
        reg.register(name, handler, validator)
    return reg


def _runtime(timeout=0.2, **kwargs):
    reg = kwargs.pop("registry", None) or _registry()
    return ToolRuntime(reg, timeout=timeout)


def test_success_status_and_output():
    result = _runtime().execute("echo", {"q": "hi"})
    assert result.status == STATUS_SUCCESS
    assert result.output["echo"] == "hi"


def test_handler_receives_context():
    result = _runtime().execute("echo", {"q": "x"}, {"run_id": "run-9"})
    assert result.output["ctx_run"] == "run-9"


def test_empty_arguments_default():
    result = _runtime().execute("echo")
    assert result.status == STATUS_SUCCESS
    assert result.output["echo"] is None


def test_failure_on_handler_exception():
    result = _runtime().execute("boom")
    assert result.status == STATUS_FAILURE
    assert result.error == "boom"


def test_timeout():
    result = _runtime(timeout=0.1).execute("slow")
    assert result.status == STATUS_TIMEOUT
    assert "timed out" in (result.error or "")


def test_metadata_timeout_honored_over_runtime_default():
    """Sprint 1.0.6.2 §27 — ToolMetadata.timeout (1.0s) overrides the
    runtime default (30s): a 6s handler times out, not completes."""
    from agent.execution.registry import SideEffectClass, ToolMetadata

    reg = ToolRegistry()
    reg.register("slow_declared", lambda a, c: (_ for _ in ()).throw(TimeoutError()),
                 metadata=ToolMetadata(side_effect_class=SideEffectClass.READ_ONLY,
                                       timeout=1.0))
    # verify the declared timeout is picked up even with a wide default
    runtime = ToolRuntime(reg, timeout=30.0)
    result = runtime.execute("slow_declared")
    assert result.status == STATUS_TIMEOUT
    assert "1.0s" in (result.error or "")


def test_unknown_tool_raises():
    with pytest.raises(ToolNotAllowed):
        _runtime().execute("nope")


def test_unknown_tool_error_carries_name():
    with pytest.raises(ToolNotAllowed) as excinfo:
        _runtime().execute("nope")
    assert excinfo.value.tool_name == "nope"
    assert "nope" in str(excinfo.value)


def test_permission_denied_without_approval():
    result = _runtime().execute("echo", {"q": "x"}, {"requires_approval": True})
    assert result.status == STATUS_PERMISSION_DENIED


def test_approved_execution_runs():
    result = _runtime().execute(
        "echo", {"q": "x"}, {"requires_approval": True, "approved": True}
    )
    assert result.status == STATUS_SUCCESS


def test_validator_called_before_execution():
    calls = []

    def validator(args):
        calls.append(dict(args))
        if args.get("q") != "ok":
            raise ValueError("bad q")

    reg = _registry(handlers={"guarded": (_echo, validator)})
    result = _runtime(registry=reg).execute("guarded", {"q": "ok"})
    assert result.status == STATUS_SUCCESS
    assert calls == [{"q": "ok"}]


def test_validation_failure_is_failure_result():
    def validator(args):
        raise ValueError("bad q")

    reg = _registry(handlers={"guarded": (_echo, validator)})
    result = _runtime(registry=reg).execute("guarded", {"q": "x"})
    assert result.status == STATUS_FAILURE
    assert "validation failed" in (result.error or "")


def test_execution_time_recorded():
    result = _runtime().execute("echo", {"q": "x"})
    assert result.execution_time >= 0.0


def test_result_to_dict():
    result = _runtime().execute("echo", {"q": "x"})
    data = result.to_dict()
    assert data["status"] == STATUS_SUCCESS
    assert data["output"]["echo"] == "x"
    assert "execution_time" in data
    assert data["error"] is None


def test_registry_allowlist_checks():
    reg = _registry()
    assert reg.has("echo") is True
    assert reg.is_allowed("echo") is True
    assert reg.is_allowed("nope") is False
    assert reg.names() == ["boom", "echo", "slow"]


def test_registry_rejects_bad_register():
    reg = ToolRegistry()
    with pytest.raises(ValueError):
        reg.register("", _echo)
    with pytest.raises(ValueError):
        reg.register("x", "not-callable")  # type: ignore[arg-type]


def test_registry_re_register_replaces():
    reg = ToolRegistry()
    reg.register("echo", lambda a, c: {"v": 1})
    assert reg.get("echo")({}, {}) == {"v": 1}
