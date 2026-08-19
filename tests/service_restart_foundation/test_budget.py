"""Sprint 1.3.12 — restart mutation budget (separate from reload, production=0)."""
from __future__ import annotations

from agent.service_restart_foundation.budget import (
    MAX_ATTEMPTS_PER_HOUR,
    MAX_SUCCESS_PER_HOUR,
    RestartBudget,
)


class TestRestartBudget:
    def test_limits(self):
        assert MAX_ATTEMPTS_PER_HOUR == 2
        assert MAX_SUCCESS_PER_HOUR == 1

    def test_fresh_budget_has_capacity(self):
        b = RestartBudget()
        assert b.remaining_attempts() == 2
        assert b.remaining_successes() == 1

    def test_attempts_consume_capacity(self):
        b = RestartBudget()
        b.record_attempt(now=0.0)
        assert b.remaining_attempts(now=1.0) == 1

    def test_success_consumes_capacity(self):
        b = RestartBudget()
        b.record_success(now=0.0)
        assert b.remaining_successes(now=1.0) == 0

    def test_production_usage_always_zero(self):
        # 1.3.12: no production mutation is ever charged to the restart budget
        b = RestartBudget()
        b.record_attempt(now=0.0)
        assert b.production_usage() == 0