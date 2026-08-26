"""AgentMessage contract tests."""

import pytest
from typing import Any

from agent.agent_orchestration.messages import (
    MessageEnvelope,
    MessagePriority,
    MessageType,
)
from agent.agent_orchestration.messages import InvalidMessage


def _env(
    message_id: str = "m1",
    schema_version: int = 1,
    from_agent: str = "planner",
    to_agent: str = "research",
    type: MessageType = MessageType.REQUEST,
    priority: MessagePriority = MessagePriority.NORMAL,
    task_id: str = "t1",
    idempotency_key: str = "k1",
    payload: tuple[Any, ...] = ("do", "work"),
    step_id: str = "",
    correlation_id: str = "",
    expires_at: float | None = None,
) -> MessageEnvelope:
    return MessageEnvelope(
        message_id=message_id,
        schema_version=schema_version,
        from_agent=from_agent,
        to_agent=to_agent,
        type=type,
        priority=priority,
        task_id=task_id,
        idempotency_key=idempotency_key,
        payload=payload,
        step_id=step_id,
        correlation_id=correlation_id,
        expires_at=expires_at,
    )


def test_valid_message():
    message = _env()
    assert message.from_agent == "planner"
    assert message.type is MessageType.REQUEST


def test_message_requires_ids():
    with pytest.raises(InvalidMessage):
        _env(message_id="")
    with pytest.raises(InvalidMessage):
        _env(from_agent="   ")


def test_payload_must_be_tuple():
    with pytest.raises(InvalidMessage):
        _env(payload="do work")  # type: ignore[arg-type]


def test_schema_version_positive():
    with pytest.raises(InvalidMessage):
        _env(schema_version=0)
    with pytest.raises(InvalidMessage):
        _env(schema_version=True)  # type: ignore[arg-type]


def test_type_and_priority_enum():
    bad_type: object = "request"
    with pytest.raises(InvalidMessage):
        MessageEnvelope(
            message_id="m1", schema_version=1, from_agent="a", to_agent="b",
            type=bad_type, priority=MessagePriority.NORMAL, task_id="t",  # type: ignore[arg-type]
            idempotency_key="k",
        )
    bad_priority: object = "high"
    with pytest.raises(InvalidMessage):
        MessageEnvelope(
            message_id="m1", schema_version=1, from_agent="a", to_agent="b",
            type=MessageType.REQUEST, priority=bad_priority, task_id="t",  # type: ignore[arg-type]
            idempotency_key="k",
        )


def test_expiry_is_expired():
    message = _env(expires_at=100.0)
    assert not message.is_expired(50.0)
    assert message.is_expired(150.0)


def test_expiry_rejects_bad_type():
    with pytest.raises(InvalidMessage):
        _env(expires_at="later")  # type: ignore[arg-type]


def test_optional_ids_normalized():
    message = _env(step_id="s1", correlation_id="c1")
    assert message.step_id == "s1"
    assert message.correlation_id == "c1"

    none_msg = MessageEnvelope(  # step_id defaults to ""
        message_id="m2", schema_version=1, from_agent="a", to_agent="b",
        type=MessageType.REQUEST, priority=MessagePriority.NORMAL,
        task_id="t", idempotency_key="k",
    )
    assert none_msg.step_id == ""


def test_to_dict_serializes():
    message = _env(correlation_id="c1")
    data = message.to_dict()
    assert data["type"] == "request"
    assert data["priority"] == 1
    assert data["correlation_id"] == "c1"


def test_message_is_data_not_authority():
    message = _env()
    assert not hasattr(message, "execute")
    assert not hasattr(message, "run")
    assert not hasattr(message, "authorize")
    assert not hasattr(message, "grant")