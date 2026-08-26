from __future__ import annotations

import inspect
import json
from dataclasses import FrozenInstanceError
from typing import get_type_hints

import pytest

from agent.agent_runtime import (
    AgentAnalysis,
    AgentExecutionContext,
    AgentPermissions,
    AgentResult,
    AgentTask,
    BaseAgent,
    ValidationResult,
)


class ConcreteAgent(BaseAgent):
    runtime_cache: dict[str, bool]

    async def analyze(self, task: object) -> object:
        return task

    async def execute(self, context: object) -> object:
        return context

    async def validate(self, result: object) -> object:
        return result


def test_base_agent_declares_async_lifecycle_as_abstract() -> None:
    assert inspect.isabstract(BaseAgent)
    assert BaseAgent.__abstractmethods__ == {"analyze", "execute", "validate"}
    for method_name in BaseAgent.__abstractmethods__:
        assert inspect.iscoroutinefunction(getattr(BaseAgent, method_name))

    with pytest.raises(TypeError):
        BaseAgent(
            agent_id="agent-1",
            role="researcher",
            capabilities=("research",),
            trust_score=0.5,
        )


def test_base_agent_lifecycle_uses_concrete_contract_types() -> None:
    assert get_type_hints(BaseAgent.analyze) == {
        "task": AgentTask,
        "return": AgentAnalysis,
    }
    assert get_type_hints(BaseAgent.execute) == {
        "context": AgentExecutionContext,
        "return": AgentResult,
    }
    assert get_type_hints(BaseAgent.validate) == {
        "result": AgentResult,
        "return": ValidationResult,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent_id", ""),
        ("agent_id", "   "),
        ("role", ""),
        ("role", "   "),
        ("capabilities", ()),
        ("capabilities", ("research", "research")),
        ("capabilities", ("research", "")),
        ("trust_score", -0.01),
        ("trust_score", 1.01),
        ("trust_score", float("nan")),
        ("trust_score", float("inf")),
    ],
)
def test_base_agent_rejects_invalid_metadata(field: str, value: object) -> None:
    metadata: dict[str, object] = {
        "agent_id": "agent-1",
        "role": "researcher",
        "capabilities": ("research",),
        "trust_score": 0.5,
    }
    metadata[field] = value

    with pytest.raises(ValueError):
        ConcreteAgent(**metadata)  # type: ignore[arg-type]


def test_base_agent_contract_metadata_is_immutable_after_construction() -> None:
    agent = ConcreteAgent(
        agent_id="agent-1",
        role="researcher",
        capabilities=("research",),
        trust_score=0.5,
    )

    for field, replacement in (
        ("id", "agent-2"),
        ("role", "executor"),
        ("capabilities", ("execute",)),
        ("trust_score", 1.0),
        ("permissions", AgentPermissions()),
    ):
        with pytest.raises(AttributeError, match="immutable"):
            setattr(agent, field, replacement)

    for field in ("id", "role", "capabilities", "trust_score", "permissions"):
        with pytest.raises(AttributeError, match="immutable"):
            delattr(agent, field)

    agent.runtime_cache = {"initialized": True}
    assert agent.runtime_cache == {"initialized": True}


def test_base_agent_defaults_to_deny_and_requires_permissions_contract() -> None:
    agent = ConcreteAgent(
        agent_id="agent-1",
        role="researcher",
        capabilities=("research",),
        trust_score=0.5,
    )

    assert agent.permissions == AgentPermissions()
    with pytest.raises(ValueError):
        ConcreteAgent(
            agent_id="agent-1",
            role="researcher",
            capabilities=("research",),
            trust_score=0.5,
            permissions=object(),  # type: ignore[arg-type]
        )

    class DerivedPermissions(AgentPermissions):
        pass

    with pytest.raises(ValueError):
        ConcreteAgent(
            agent_id="agent-1",
            role="researcher",
            capabilities=("research",),
            trust_score=0.5,
            permissions=DerivedPermissions(),
        )


def test_agent_task_is_immutable_and_bounded() -> None:
    task = AgentTask(task_id="task-1", input="inspect repository")

    with pytest.raises(FrozenInstanceError):
        task.input = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError):
        AgentTask(task_id="task-1", input="x" * 65_537)
    with pytest.raises(ValueError):
        AgentTask(task_id="x" * 65_537, input="inspect repository")


def test_lifecycle_models_are_immutable_and_bounded() -> None:
    analysis = AgentAnalysis(
        summary="ready",
        required_capabilities=("read_files",),
    )
    context = AgentExecutionContext(
        task_id="task-1",
        step_id="step-1",
        run_id="run-1",
        input="inspect repository",
        context="only relevant files",
        memory_references=("memory-1",),
        memory_snippets=("sanitized",),
        permission_grant_reference="grant-1",
        idempotency_key="key-1",
        approved_capabilities=("read_files",),
    )
    result = AgentResult(run_id="run-1", output="done")
    validation = ValidationResult(valid=True, reason="verified")

    for instance, attribute in (
        (analysis, "summary"),
        (context, "input"),
        (result, "output"),
        (validation, "reason"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(instance, attribute, "changed")

    with pytest.raises(ValueError):
        AgentAnalysis(summary="x" * 65_537)
    with pytest.raises(ValueError):
        AgentResult(run_id="run-1", output="x" * 65_537)
    with pytest.raises(ValueError):
        ValidationResult(valid=False, reason="x" * 65_537)


@pytest.mark.parametrize(
    "deadline",
    (float("nan"), float("inf"), float("-inf"), -0.01, 10**10000),
    ids=("nan", "positive-infinity", "negative-infinity", "negative", "huge-int"),
)
def test_execution_context_rejects_nonfinite_or_negative_deadline(
    deadline: int | float,
) -> None:
    with pytest.raises(ValueError, match="deadline"):
        AgentExecutionContext(
            task_id="task-1",
            step_id="step-1",
            run_id="run-1",
            input="safe input",
            deadline=deadline,
        )


def test_execution_context_serialization_has_only_sanitized_data() -> None:
    context = AgentExecutionContext(
        task_id="task-1",
        step_id="step-1",
        run_id="run-1",
        input="safe input",
        context="safe context",
        memory_references=("memory-1",),
        memory_snippets=("safe snippet",),
        deadline=100.0,
        cancellation_token="cancel-1",
        permission_grant_reference="grant-1",
        idempotency_key="key-1",
        approved_capabilities=("read_files",),
    )

    serialized = context.to_dict()

    assert set(serialized) == {
        "task_id",
        "step_id",
        "run_id",
        "input",
        "context",
        "memory_references",
        "memory_snippets",
        "deadline",
        "cancellation_token",
        "permission_grant_reference",
        "idempotency_key",
        "approved_capabilities",
    }
    encoded = json.dumps(serialized).lower()
    assert "credential" not in encoded
    assert "system_prompt" not in encoded
    assert "executor" not in encoded
    assert "tool_object" not in encoded
