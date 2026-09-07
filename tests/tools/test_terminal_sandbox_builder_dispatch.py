"""Regression coverage for sandbox backend dispatch.

Built-in sandbox builders are functools.partial instances with env_type
already bound positionally. _create_environment must therefore not pass
env_type to built-in builders a second time.

Plugin backends still require env_type for provider lookup.
"""

import pytest

from tools import terminal_tool_backends as backends


class _FakeEnvironment:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.mark.parametrize(
    "env_type",
    [
        "singularity",
        "daytona",
        "vercel_sandbox",
    ],
)
def test_create_environment_does_not_duplicate_env_type_for_sandbox_builders(
    monkeypatch,
    env_type,
):
    monkeypatch.setitem(
        backends._SANDBOX_ROWS,
        env_type,
        (
            lambda: _FakeEnvironment,
            False,
            lambda cc, kw: {},
        ),
    )

    env = backends._create_environment(
        env_type=env_type,
        image="unused",
        cwd="/tmp",
        timeout=1,
        container_config={},
        task_id="sandbox-dispatch-regression",
    )

    assert isinstance(env, _FakeEnvironment)
    assert env.kwargs["cwd"] == "/tmp"
    assert env.kwargs["timeout"] == 1
    assert env.kwargs["task_id"] == "sandbox-dispatch-regression"


def test_builtin_builder_dispatch_does_not_receive_env_type(monkeypatch):
    received = {}

    def fake_builder(**kwargs):
        received.update(kwargs)
        return object()

    monkeypatch.setitem(backends._ENV_BUILDERS, "local", fake_builder)

    backends._create_environment(
        env_type="local",
        image="unused",
        cwd="/tmp",
        timeout=1,
        container_config={},
        task_id="builtin-dispatch-regression",
    )

    assert "env_type" not in received


def test_plugin_builder_dispatch_still_receives_env_type(monkeypatch):
    received = {}

    def fake_plugin_builder(**kwargs):
        received.update(kwargs)
        return object()

    monkeypatch.setattr(backends, "_build_plugin_env", fake_plugin_builder)

    backends._create_environment(
        env_type="synthetic_plugin_backend",
        image="unused",
        cwd="/tmp",
        timeout=1,
        container_config={},
        task_id="plugin-dispatch-regression",
    )

    assert received["env_type"] == "synthetic_plugin_backend"
