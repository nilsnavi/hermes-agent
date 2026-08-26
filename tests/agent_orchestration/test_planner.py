"""Planner tests."""

import pytest

from agent.agent_orchestration.analyzer import TaskAnalysis, TaskAnalyzer
from agent.agent_orchestration.planner import InvalidPlan, PlannedStep, Planner


def _analysis(goal="do the work") -> TaskAnalysis:
    return TaskAnalyzer.analyze(goal, "t1")


def _steps():
    return (
        PlannedStep("s1", "research", ("file_read",)),
        PlannedStep("s2", "write", ("file_write",), frozenset({"s1"})),
    )


def test_planner_builds_valid_plan():
    plan = Planner.plan(
        _analysis(), plan_id="p1", tenant_id="ten", user_id="u", steps=_steps(),
    )
    assert plan.task_id == "t1"
    assert len(tuple(plan.steps)) == 2


def test_planner_validates_dag_cycle():
    from agent.agent_orchestration.task_graph import InvalidTaskGraph

    cyclic = (
        PlannedStep("a", "x", ("c1",), frozenset({"b"})),
        PlannedStep("b", "y", ("c1",), frozenset({"a"})),
    )
    with pytest.raises(InvalidTaskGraph):
        Planner.plan(_analysis(), plan_id="p", tenant_id="t", user_id="u", steps=cyclic)


def test_planner_rejects_missing_capability():
    available = {"file_read"}
    with pytest.raises(InvalidPlan):
        Planner.plan(
            _analysis(), plan_id="p", tenant_id="t", user_id="u",
            steps=_steps(), available_capabilities=available,
        )


def test_planner_requires_at_least_one_step():
    with pytest.raises(InvalidPlan):
        Planner.plan(_analysis(), plan_id="p", tenant_id="t", user_id="u", steps=())


def test_planner_requires_tenant_user():
    with pytest.raises(InvalidPlan):
        Planner.plan(_analysis(), plan_id="p", tenant_id="", user_id="u", steps=_steps())


def test_planner_scope_mismatch_rejected():
    # A step whose tenant differs from the plan is a DAG scope violation.
    from agent.agent_orchestration.models import TaskStep, TaskPlan
    from agent.agent_orchestration.task_graph import InvalidTaskGraph

    # Planner keeps step scope equal to plan scope, so a mismatch cannot arise
    # here; guarded by TaskGraph. Verify via direct graph construction.
    ok = Planner.plan(
        _analysis(), plan_id="p", tenant_id="t", user_id="u", steps=_steps()
    )
    assert ok.tenant_id == "t"
    # A hand-built mismatched plan is rejected by the graph.
    bad_step = TaskStep("s1", "t1", "other-tenant", "u", frozenset())
    bad_plan = TaskPlan("p", "t1", "t", "u", (bad_step,))
    with pytest.raises(InvalidTaskGraph):
        from agent.agent_orchestration.task_graph import TaskGraph
        TaskGraph(bad_plan)


def test_planner_has_no_execution_surface():
    assert not hasattr(Planner, "execute")
    assert not hasattr(Planner, "run")
    assert not hasattr(Planner, "dispatch")
    assert not hasattr(Planner, "authorize")