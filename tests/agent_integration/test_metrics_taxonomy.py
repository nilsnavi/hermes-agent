"""Error taxonomy (Phase 6 §25) + observability metrics (§31)."""

import threading

import pytest

from agent.agent_integration.error_taxonomy import (
    NON_SUCCESS_OUTCOMES,
    AgentOutcome,
)
from agent.agent_integration.metrics import METRIC_NAMES, MetricsError, MetricsRegistry


def test_outcomes_are_typed_and_complete():
    expected = {
        "AGENT_COMPLETED", "AGENT_FAILED_SAFE", "AGENT_TIMEOUT", "AGENT_UNKNOWN",
        "AGENT_HUMAN_REVIEW", "NO_ROUTE", "POLICY_DENIED", "BOUNDARY_DENIED",
        "MEMORY_DENIED", "REGISTRY_DRIFT",
    }
    assert {o.name for o in AgentOutcome} == expected


def test_no_generic_boolean_success():
    # A boolean "success" must not be the outcome model; a typed outcome is used.
    assert isinstance(AgentOutcome.AGENT_COMPLETED, AgentOutcome)
    assert AgentOutcome.AGENT_COMPLETED not in NON_SUCCESS_OUTCOMES


def test_non_success_set_is_correct():
    assert AgentOutcome.AGENT_COMPLETED not in NON_SUCCESS_OUTCOMES
    for o in (AgentOutcome.AGENT_FAILED_SAFE, AgentOutcome.POLICY_DENIED,
              AgentOutcome.REGISTRY_DRIFT, AgentOutcome.BOUNDARY_DENIED):
        assert o in NON_SUCCESS_OUTCOMES


def test_metrics_names_are_closed_and_fixed():
    assert METRIC_NAMES == {
        "tasks_created", "tasks_completed", "tasks_failed", "tasks_human_review",
        "agent_runs", "agent_run_duplicates", "route_denials", "registry_drift",
        "memory_denials", "boundary_denials", "message_duplicates",
        "cross_tenant_denials",
    }


def test_metrics_increment_and_snapshot():
    m = MetricsRegistry()
    assert m.increment("agent_runs") == 1
    assert m.increment("agent_runs") == 2
    assert m.increment("tasks_completed", by=3) == 3
    assert m.snapshot()["agent_runs"] == 2
    assert len(m) == len(METRIC_NAMES)


def test_metrics_reject_unknown_name():
    m = MetricsRegistry()
    with pytest.raises(MetricsError):
        m.increment("not_a_metric")
    with pytest.raises(MetricsError):
        m.get("user_specific_secret")  # no identifier leaks into labels


def test_metrics_match_required_categories():
    required = {
        "tasks_created", "tasks_completed", "tasks_failed", "tasks_human_review",
        "agent_runs", "agent_run_duplicates", "route_denials", "registry_drift",
        "memory_denials", "boundary_denials", "message_duplicates",
        "cross_tenant_denials",
    }
    assert METRIC_NAMES.issuperset(required)


def test_metrics_are_thread_safe():
    m = MetricsRegistry()
    errors: list[BaseException] = []

    def worker():
        try:
            for _ in range(200):
                m.increment("agent_runs")
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert m.get("agent_runs") == 8 * 200