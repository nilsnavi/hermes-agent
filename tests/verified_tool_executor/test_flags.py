"""Sprint 1.3.2 §61 — feature flag: off by default, fail closed."""

from agent.verified_tool_executor.flags import (
    EXECUTOR_ENV,
    parse_executor_flag,
    read_executor_flags,
)


def test_flag_default_off():
    assert parse_executor_flag(None) is False
    assert parse_executor_flag("") is False


def test_flag_true_variants():
    for v in ("true", "TRUE", "True", "1", "yes", "on"):
        assert parse_executor_flag(v) is True


def test_flag_false_variants():
    for v in ("false", "FALSE", "0", "no", "off"):
        assert parse_executor_flag(v) is False


def test_flag_garbage_fails_closed():
    assert parse_executor_flag("bogus") is False
    assert parse_executor_flag("enforce") is False  # not a mode
    assert parse_executor_flag("2") is False


def test_read_executor_flags_env():
    env = {EXECUTOR_ENV: "true"}
    assert read_executor_flags(env)["verified_tool_executor_v2"] is True
    env2 = {EXECUTOR_ENV: "garbage"}
    assert read_executor_flags(env2)["verified_tool_executor_v2"] is False
    assert read_executor_flags({})["verified_tool_executor_v2"] is False
