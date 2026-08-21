"""Test executor: typed, exact allowlist, no raw command, adapter counter."""
import tempfile, os
from agent.service_restart_canary.allowlist import default_allowlist, CANARY_SERVICE_ID, CANARY_UNIT
from agent.service_restart_canary.executor import (RestartExecutor, FakeRestartAdapter,
                                                    public_operation, stop_or_start_denied)
from agent.service_restart_canary.models import RestartExecutionRequest, Operation


def test_kill_switch_blocks():
    d = tempfile.mkdtemp()
    al = default_allowlist()
    ex = RestartExecutor(al, adapter=FakeRestartAdapter(), store_dir=d, kill_switch=True)
    req = RestartExecutionRequest(service_id=CANARY_SERVICE_ID, verified_unit_identity=CANARY_UNIT, transaction_id="t1")
    outcome, calls = ex.execute(req)
    assert outcome == "CANARY_DISABLED"
    assert calls == 0


def test_unregistered_denied():
    d = tempfile.mkdtemp()
    al = default_allowlist()
    ex = RestartExecutor(al, adapter=FakeRestartAdapter(), store_dir=d, kill_switch=False)
    req = RestartExecutionRequest(service_id="ghost", verified_unit_identity="ghost.service", transaction_id="t1")
    outcome, calls = ex.execute(req)
    assert outcome == "NOT_REGISTERED"
    assert calls == 0


def test_wrong_unit_identity():
    d = tempfile.mkdtemp()
    al = default_allowlist()
    ex = RestartExecutor(al, adapter=FakeRestartAdapter(), store_dir=d, kill_switch=False)
    req = RestartExecutionRequest(service_id=CANARY_SERVICE_ID, verified_unit_identity="wrong.service", transaction_id="t1")
    outcome, _ = ex.execute(req)
    assert outcome == "UNIT_IDENTITY_MISMATCH"


def test_fake_execute_ok():
    d = tempfile.mkdtemp()
    al = default_allowlist()
    fa = FakeRestartAdapter()
    ex = RestartExecutor(al, adapter=fa, store_dir=d, kill_switch=False)
    req = RestartExecutionRequest(service_id=CANARY_SERVICE_ID, verified_unit_identity=CANARY_UNIT, transaction_id="t1")
    outcome, calls = ex.execute(req)
    assert outcome == "EXECUTED"
    assert calls == 1
    assert fa.calls == 1


def test_adapter_counter_durable():
    d = tempfile.mkdtemp()
    al = default_allowlist()
    ex1 = RestartExecutor(al, adapter=FakeRestartAdapter(), store_dir=d, kill_switch=False)
    req = RestartExecutionRequest(service_id=CANARY_SERVICE_ID, verified_unit_identity=CANARY_UNIT, transaction_id="t1")
    ex1.execute(req)
    # new executor reads same counter
    ex2 = RestartExecutor(al, adapter=FakeRestartAdapter(), store_dir=d, kill_switch=False)
    assert ex2.adapter_calls() == 1


def test_stop_start_denied():
    assert stop_or_start_denied() == "OPERATION_DENIED"
    r, c = public_operation(None, "STOP")
    assert r == "OPERATION_DENIED"
    assert c == 0
    r, c = public_operation(None, "START")
    assert r == "OPERATION_DENIED"
    assert c == 0
    r, c = public_operation(None, "KILL")
    assert r == "OPERATION_DENIED"
    assert c == 0


def test_no_raw_command():
    """Executor accepts only typed RestartExecutionRequest, not shell strings."""
    from agent.service_restart_canary.executor import RestartExecutor
    assert not hasattr(RestartExecutor, "restart_command")
    assert not hasattr(RestartExecutor, "systemctl")
