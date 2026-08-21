"""Test restart budget: separate from reload, 1 success / 2 attempts."""
from agent.service_restart_canary.budget import RestartBudget, MAX_SUCCESSFUL_RESTARTS, MAX_TOTAL_RESTART_ATTEMPTS


def test_defaults():
    b = RestartBudget()
    assert b.remaining_attempts() == MAX_TOTAL_RESTART_ATTEMPTS
    assert b.remaining_successes() == MAX_SUCCESSFUL_RESTARTS


def test_allow_attempt():
    b = RestartBudget()
    assert b.allow_attempt() is True
    assert b.allow_attempt() is True
    assert b.allow_attempt() is False  # exhausted
    assert b.attempts() == 2


def test_record_success():
    b = RestartBudget()
    b.allow_attempt()
    b.record_success()
    assert b.successes() == 1
    assert b.remaining_successes() == 0


def test_success_prevents_more():
    b = RestartBudget()
    b.allow_attempt()
    b.record_success()
    b.allow_attempt()
    b.record_success()  # no effect
    assert b.successes() == 1
