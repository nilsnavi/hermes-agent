"""Platform API request/response contracts.

Typed, bounded data contracts for the platform REST surface. They are pure
value models: they validate and version request/response payloads but carry no
execution authority and perform no work. Requests that carry an idempotency key
expose it so the transaction boundary can enforce exactly-once processing.
"""

from __future__ import annotations

from dataclasses import dataclass


class InvalidSchema(ValueError):
    """Raised when an API request/response contract receives invalid data."""


def _require_str(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise InvalidSchema(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise InvalidSchema(f"{name} must be a non-empty string")
    return value


def _require_bounded_str(
    value: object, name: str, maximum: int = 4096, *, allow_empty: bool = False
) -> str:
    if not isinstance(value, str):
        raise InvalidSchema(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise InvalidSchema(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise InvalidSchema(f"{name} exceeds {maximum} characters")
    return value


@dataclass(frozen=True, slots=True)
class AgentsListResponse:
    items: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise InvalidSchema("items must be a tuple")
        for item in self.items:
            _require_str(item, "agent_id")


@dataclass(frozen=True, slots=True)
class RegisterAgentRequest:
    agent_id: str
    role: str
    implementation_id: str
    capabilities: tuple[str, ...]
    name: str = ""

    def __post_init__(self) -> None:
        _require_bounded_str(self.agent_id, "agent_id")
        _require_bounded_str(self.role, "role")
        _require_bounded_str(self.implementation_id, "implementation_id")
        _require_bounded_str(self.name, "name", allow_empty=True)
        if not isinstance(self.capabilities, tuple):
            raise InvalidSchema("capabilities must be a tuple")


@dataclass(frozen=True, slots=True)
class TaskSubmitRequest:
    goal: str
    idempotency_key: str
    tenant: str = ""

    def __post_init__(self) -> None:
        _require_bounded_str(self.goal, "goal")
        _require_bounded_str(self.idempotency_key, "idempotency_key")
        # tenant is supplied by the authenticated principal, not the body.
        _require_bounded_str(self.tenant, "tenant", allow_empty=True)


@dataclass(frozen=True, slots=True)
class TaskSubmitResponse:
    task_id: str
    status: str
    version: int

    def __post_init__(self) -> None:
        _require_str(self.task_id, "task_id")
        _require_str(self.status, "status")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 0:
            raise InvalidSchema("version must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class MemorySearchRequest:
    query: str
    tenant: str = ""
    limit: int = 10

    def __post_init__(self) -> None:
        _require_bounded_str(self.query, "query")
        _require_bounded_str(self.tenant, "tenant", allow_empty=True)
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit < 1 or self.limit > 100:
            raise InvalidSchema("limit must be an int in [1, 100]")


@dataclass(frozen=True, slots=True)
class MemoryStoreRequest:
    content: str
    idempotency_key: str
    tenant: str = ""

    def __post_init__(self) -> None:
        _require_bounded_str(self.content, "content")
        _require_bounded_str(self.idempotency_key, "idempotency_key")
        _require_bounded_str(self.tenant, "tenant", allow_empty=True)


# Canonical mutation endpoints require an idempotency key — encode this rule so
# a router cannot forget it.
MUTATING_ENDPOINTS_REQUIRE_IDEMPOTENCY: frozenset[str] = frozenset(
    {
        "POST /tasks",
        "POST /memory/store",
        "POST /agents/register",
    }
)