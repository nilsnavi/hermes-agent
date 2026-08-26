"""API request/response schema contract tests."""

import pytest

from agent.platform_api.schemas import (
    AgentsListResponse,
    MUTATING_ENDPOINTS_REQUIRE_IDEMPOTENCY,
    InvalidSchema,
    RegisterAgentRequest,
    TaskSubmitRequest,
    TaskSubmitResponse,
)


def test_task_submit_requires_goal_and_idempotency():
    TaskSubmitRequest(goal="do work", idempotency_key="k-1")
    with pytest.raises(InvalidSchema):
        TaskSubmitRequest(goal="", idempotency_key="k-1")
    with pytest.raises(InvalidSchema):
        TaskSubmitRequest(goal="do work", idempotency_key="")


def test_task_submit_response_validates():
    TaskSubmitResponse(task_id="t1", status="created", version=0)
    with pytest.raises(InvalidSchema):
        TaskSubmitResponse(task_id="", status="created", version=0)
    with pytest.raises(InvalidSchema):
        TaskSubmitResponse(task_id="t1", status="created", version=-1)


def test_register_agent_requires_implementation():
    capabilities: tuple[str, ...] = ("file_read",)
    RegisterAgentRequest(
        agent_id="a1", role="research", implementation_id="research-v1",
        capabilities=capabilities,
    )
    with pytest.raises(InvalidSchema):
        RegisterAgentRequest(
            agent_id="a1", role="research", implementation_id="",
            capabilities=capabilities,
        )
    with pytest.raises(InvalidSchema):
        RegisterAgentRequest(
            agent_id="a1", role="research", implementation_id="x",
            capabilities="file_read",  # type: ignore[arg-type]
        )


def test_agents_list_response_validates():
    AgentsListResponse(items=("a1",))
    with pytest.raises(InvalidSchema):
        AgentsListResponse(items=("",))


def test_mutating_endpoints_require_idempotency_key():
    # Every mutation endpoint in the contract must carry an idempotency key.
    assert "POST /tasks" in MUTATING_ENDPOINTS_REQUIRE_IDEMPOTENCY
    assert "POST /memory/store" in MUTATING_ENDPOINTS_REQUIRE_IDEMPOTENCY
    assert "POST /agents/register" in MUTATING_ENDPOINTS_REQUIRE_IDEMPOTENCY


def test_schema_contracts_carry_no_execution_authority():
    request = TaskSubmitRequest(goal="g", idempotency_key="k")
    assert not hasattr(request, "execute")
    assert not hasattr(request, "run")