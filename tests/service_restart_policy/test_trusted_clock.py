import inspect

import pytest

from agent.service_restart_policy import ControlledClock
from agent.service_restart_policy.approval import ApprovalContract, DurableApprovalStore
from agent.service_restart_policy.breaker import DurableCircuitBreaker
from agent.service_restart_policy.budget import DurableHourlyBudgets
from agent.service_restart_policy.lock import HardenedServiceLock
from agent.service_restart_policy.runtime import LimitedRestartRuntime


def _contract(**changes):
    values = dict(
        approval_id="approval",
        service_id="hermes-aux-canary",
        profile_version=1,
        transaction_id="tx",
        old_process_identity="identity",
        graph_digest="graph",
        consumer_state="NONE",
        config_digest="config",
        health_digest="health",
        risk="HIGH",
        blast="SERVICE",
        quiescence_contract="q",
        startup_contract="s",
        recovery_contract="r",
        budget_snapshot="budget",
        breaker_snapshot="closed",
        plan_hash="plan",
        baseline_sha="baseline",
        expires_at=110,
        plan_expires_at=105,
    )
    values.update(changes)
    return ApprovalContract(**values)


def test_runtime_authority_api_does_not_accept_caller_now():
    parameters = inspect.signature(LimitedRestartRuntime.execute).parameters
    assert "now" not in parameters


def test_runtime_constructor_accepts_injected_clock_not_request_time():
    parameters = inspect.signature(LimitedRestartRuntime.__init__).parameters
    assert "clock" in parameters


def test_request_old_new_or_future_now_is_not_accepted(tmp_path):
    runtime = LimitedRestartRuntime(tmp_path, runner=lambda *args, **kwargs: None)
    for value in (-1, 0, 10**30):
        with pytest.raises(TypeError):
            runtime.execute(object(), object(), object(), now=value)


def test_approval_and_plan_expiry_cannot_be_extended_by_caller(tmp_path):
    store = DurableApprovalStore(tmp_path)
    contract = _contract()
    store.issue_contract(contract)
    assert store.validate_contract(contract, 100) == "APPROVED"
    assert store.validate_contract(contract, 106) == "PLAN_EXPIRED"
    assert store.validate_contract(contract, 111) == "APPROVAL_EXPIRED"
    forged = _contract(expires_at=1000, plan_expires_at=1000)
    assert store.validate_contract(forged, 106) == "APPROVAL_BINDING_MISMATCH"


def test_budget_window_and_breaker_cooldown_use_authority_clock_values(tmp_path):
    clock = ControlledClock(100, 100)
    budget = DurableHourlyBudgets(
        tmp_path / "budget", per_service_attempts=1, per_service_successes=1,
        global_attempts=1, global_successes=1,
    )
    assert budget.reserve_attempt("svc", clock.monotonic(), "reservation")
    assert not budget.reserve_attempt("svc", clock.monotonic(), "other")
    clock.advance(3601)
    assert budget.reserve_attempt("svc", clock.monotonic(), "after-window")

    breaker = DurableCircuitBreaker(tmp_path / "breaker", threshold=1, cooldown=60)
    breaker.record_failure("svc", clock.monotonic())
    assert not breaker.allow("svc", clock.monotonic())
    clock.advance(61)
    assert breaker.allow("svc", clock.monotonic())


def test_lock_ttl_cannot_evict_live_owner_even_when_clock_advances(tmp_path):
    clock = ControlledClock(100, 100)
    starts = {1: "one", 2: "two"}
    lock = HardenedServiceLock(tmp_path, process_start=starts.get, ttl=10)
    assert lock.acquire("svc", 1, "one", "n1", clock.monotonic(), "tx1")
    clock.advance(1000)
    assert not lock.acquire("svc", 2, "two", "n2", clock.monotonic(), "tx2")


def test_persisted_monotonic_state_fails_closed_across_clock_provenance(tmp_path):
    LimitedRestartRuntime(
        tmp_path,
        runner=lambda *args, **kwargs: None,
        clock=ControlledClock(100, 100, "boot-a"),
    )
    calls = []
    runtime = LimitedRestartRuntime(
        tmp_path,
        runner=lambda *args, **kwargs: calls.append(1),
        rollout_enabled=True,
        kill_switch=False,
        clock=ControlledClock(100, 100, "boot-b"),
    )
    result = runtime.execute(object(), object(), object())
    assert result.outcome == "CLOCK_PROVENANCE_MISMATCH"
    assert calls == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True])
def test_nonfinite_or_bool_controlled_clock_fails_closed(tmp_path, value):
    runtime = LimitedRestartRuntime(
        tmp_path,
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("adapter must not run")
        ),
        rollout_enabled=True,
        kill_switch=False,
        clock=ControlledClock(value, 100),
    )
    result = runtime.execute(object(), object(), object())
    assert result.outcome == "INVALID_TIME"
    assert result.adapter_calls == 0
