"""Test gateway self-control: all ops -> SELF_CONTROL_FORBIDDEN, adapter=0."""
from agent.service_restart_canary.gateway import gateway_self_control, FORBIDDEN_GATEWAY_OPS


def test_restart_forbidden():
    r = gateway_self_control("restart")
    assert r.result == "SELF_CONTROL_FORBIDDEN"
    assert r.execution == 0


def test_stop_forbidden():
    r = gateway_self_control("stop")
    assert r.result == "SELF_CONTROL_FORBIDDEN"
    assert r.execution == 0


def test_start_forbidden():
    r = gateway_self_control("start")
    assert r.result == "SELF_CONTROL_FORBIDDEN"
    assert r.execution == 0


def test_kill_signal_forbidden():
    r = gateway_self_control("kill")
    assert r.result == "SELF_CONTROL_FORBIDDEN"
    assert r.execution == 0
    r2 = gateway_self_control("signal")
    assert r2.result == "SELF_CONTROL_FORBIDDEN"


def test_reload_forbidden():
    r = gateway_self_control("reload")
    assert r.result == "SELF_CONTROL_FORBIDDEN"
    assert r.execution == 0


def test_all_ops_listed():
    for op in ("restart", "reload", "stop", "start", "kill", "signal"):
        assert op in FORBIDDEN_GATEWAY_OPS
