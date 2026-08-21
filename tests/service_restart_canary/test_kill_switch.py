"""Test kill switch: after live success ENABLED=false blocks restart."""
from agent.service_restart_canary.allowlist import CANARY_SERVICE_ID, CANARY_UNIT
from agent.service_restart_canary.executor import RestartExecutor, FakeRestartAdapter
from agent.service_restart_canary.flags import enabled, canary_active, mode


def test_flag_off_disables():
    assert enabled({"HERMES_SERVICE_RESTART_CANARY_V2_ENABLED": "false"}) is False
    assert canary_active({"HERMES_SERVICE_RESTART_CANARY_V2_ENABLED": "false",
                          "HERMES_SERVICE_RESTART_CANARY_V2_MODE": "canary"}) is False


def test_kill_switch_blocks_execute():
    d = "/tmp/ks-test"
    from agent.service_restart_canary.allowlist import default_allowlist
    ex = RestartExecutor(default_allowlist(), adapter=FakeRestartAdapter(),
                         store_dir=d, kill_switch=True)
    from agent.service_restart_canary.models import RestartExecutionRequest
    req = RestartExecutionRequest(CANARY_SERVICE_ID, CANARY_UNIT, "t1")
    outcome, calls = ex.execute(req)
    assert outcome == "CANARY_DISABLED"
    assert calls == 0