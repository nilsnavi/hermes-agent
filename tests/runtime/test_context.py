"""TaskContext tests (Sprint 1.0.1)."""

import pytest

from agent.runtime.context import TaskContext


def test_creation_with_defaults():
    ctx = TaskContext(goal="Generate CRM report")
    assert ctx.goal == "Generate CRM report"
    assert ctx.constraints == []
    assert ctx.allowed_tools == []
    assert ctx.metadata == {}
    assert ctx.risk_level == "low"
    assert ctx.approval_required is False


def test_full_serialization_roundtrip():
    ctx = TaskContext(
        goal="Generate CRM report",
        constraints=["require approval before send"],
        allowed_tools=["github", "jira"],
        metadata={"source": "crm", "tenant": "acme"},
        risk_level="medium",
        approval_required=True,
    )
    data = ctx.to_dict()
    assert data == {
        "goal": "Generate CRM report",
        "constraints": ["require approval before send"],
        "allowed_tools": ["github", "jira"],
        "metadata": {"source": "crm", "tenant": "acme"},
        "risk_level": "medium",
        "approval_required": True,
    }
    assert TaskContext.from_dict(data) == ctx


def test_goal_is_mandatory():
    with pytest.raises(KeyError):
        TaskContext.from_dict({"risk_level": "high"})


def test_from_dict_tolerates_optional_fields():
    ctx = TaskContext.from_dict({"goal": "hi"})
    assert ctx.constraints == []
    assert ctx.risk_level == "low"
    assert ctx.approval_required is False
