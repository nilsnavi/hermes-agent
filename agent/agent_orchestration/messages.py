"""AgentMessage contract and message envelope.

AgentMessage is the transport envelope for intra-platform agent coordination.
It carries intent, correlation, and idempotency metadata but NEVER carries
execution authority: a message may describe a request, but it cannot mint the
right for any recipient to run a tool. Execution permission comes only from the
verified execution kernel; a message is data, not a grant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any


class MessageType(Enum):
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"
    FEEDBACK = "feedback"
    ERROR = "error"


class MessagePriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class InvalidMessage(ValueError):
    """Raised when an agent message violates its contract."""


MAX_ID_LENGTH = 256
MAX_PAYLOAD_SIZE = 64 * 1024  # 64 KiB
MAX_CORRELATION_LENGTH = 256
MAX_ATTEMPT = 2**31 - 1
MAX_PAYLOAD_ELEMENTS = 128
MAX_PAYLOAD_STRING_LENGTH = 65_536
MAX_INT_MAGNITUDE = 2**63
MAX_PAYLOAD_DEPTH = 6

# Per architectural doc §6: the five canonical message types.
CANONICAL_MESSAGE_TYPES = frozenset(MessageType)


def _require_bounded_id(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidMessage(f"{name} must be a non-empty string")
    if len(value) > MAX_ID_LENGTH:
        raise InvalidMessage(f"{name} exceeds {MAX_ID_LENGTH} characters")
    return value


def _require_optional_bounded_id(name: str, value: object) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise InvalidMessage(f"{name} must be a string or None")
    return _require_bounded_id(name, value)


def _is_canonical_scalar(value: object, depth: int) -> None:
    """ORCH-001: enforce canonical serializable values (str/int/float/bool/None).

    Rejects callables, file handles, classes, modules, and any arbitrary
    executor/adapter/authority object. Containers (tuple/list/dict) are allowed
    only when bounded and recursively canonical; dict keys must be bounded str.
    """
    if depth > MAX_PAYLOAD_DEPTH:
        raise InvalidMessage("payload nesting exceeds the bounded depth")
    if value is None:
        return
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_INT_MAGNITUDE:
            raise InvalidMessage("int payload element exceeds the bounded range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidMessage("non-finite float payload element is forbidden")
        return
    if isinstance(value, str):
        if len(value) > MAX_PAYLOAD_STRING_LENGTH:
            raise InvalidMessage("string payload element exceeds the bounded length")
        return
    if isinstance(value, (tuple, list)):
        if len(value) > MAX_PAYLOAD_ELEMENTS:
            raise InvalidMessage("payload container exceeds the bounded element count")
        for item in value:
            _is_canonical_scalar(item, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_PAYLOAD_ELEMENTS:
            raise InvalidMessage("payload container exceeds the bounded element count")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > MAX_PAYLOAD_STRING_LENGTH:
                raise InvalidMessage("payload dict keys must be bounded strings")
            _is_canonical_scalar(item, depth + 1)
        return
    raise InvalidMessage(
        f"payload element of type {type(value).__name__} is not canonical "
        "serializable (callables/objects/executors/adapters/authority forbidden)"
    )


def _require_sanitized_payload(payload: object) -> tuple[Any, ...]:
    # Payload must be a bounded tuple so schema validation and redaction can
    # treat it as shape-checked data, not as an executable directive. Every
    # element is validated to be canonical serializable (ORCH-001).
    if not isinstance(payload, tuple):
        raise InvalidMessage("payload must be a tuple")
    if len(payload) > 128:
        raise InvalidMessage("payload exceeds 128 items")
    for item in payload:
        _is_canonical_scalar(item, 0)
    return payload


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    """Immutable, self-contained message container for bus delivery."""

    message_id: str
    schema_version: int
    from_agent: str
    to_agent: str
    type: MessageType
    priority: MessagePriority
    task_id: str
    idempotency_key: str
    payload: tuple[Any, ...] = ()
    step_id: str = ""
    run_id: str = ""
    correlation_id: str = ""
    causation_id: str = ""
    expires_at: float | None = None

    def __post_init__(self) -> None:
        for name in ("message_id", "from_agent", "to_agent", "task_id", "idempotency_key"):
            object.__setattr__(self, name, _require_bounded_id(name, getattr(self, name)))
        object.__setattr__(self, "step_id", _require_optional_bounded_id("step_id", self.step_id))
        object.__setattr__(self, "run_id", _require_optional_bounded_id("run_id", self.run_id))
        object.__setattr__(self, "correlation_id", _require_optional_bounded_id("correlation_id", self.correlation_id))
        object.__setattr__(self, "causation_id", _require_optional_bounded_id("causation_id", self.causation_id))
        object.__setattr__(self, "payload", _require_sanitized_payload(self.payload))
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int) or self.schema_version < 1:
            raise InvalidMessage("schema_version must be a positive integer")
        if type(self.type) is not MessageType:
            raise InvalidMessage("type must be an exact MessageType value")
        if type(self.priority) is not MessagePriority:
            raise InvalidMessage("priority must be an exact MessagePriority value")
        if self.expires_at is not None:
            if isinstance(self.expires_at, bool) or not isinstance(self.expires_at, (int, float)):
                raise InvalidMessage("expires_at must be a number or None")
            if self.expires_at < 0:
                raise InvalidMessage("expires_at must be non-negative")

    def is_expired(self, now: float) -> bool:
        if isinstance(now, bool) or not isinstance(now, (int, float)):
            raise InvalidMessage("now must be a number")
        if self.expires_at is not None and now > self.expires_at:
            return True
        return False

    def to_dict(self) -> dict[str, object]:
        return {
            "message_id": self.message_id,
            "schema_version": self.schema_version,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "type": self.type.value,
            "priority": self.priority.value,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "idempotency_key": self.idempotency_key,
            "pure_payload": self.payload,
            "expires_at": self.expires_at,
        }


AgentMessage = MessageEnvelope
"""Alias for the AgentMessage contract (architectural name)."""