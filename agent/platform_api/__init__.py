"""Platform API contracts: schemas, auth boundaries, versioning.

This package defines the typed surface of the platform REST API. It is pure
contract data (stdlib-only) with zero execution authority: no servers, no DB
connections, no tool calls.
"""

from .auth import (
    AuthenticationError,
    Principal,
    authenticate_bearer,
    enforce_tenant_boundary,
)
from .schemas import (
    AgentsListResponse,
    MUTATING_ENDPOINTS_REQUIRE_IDEMPOTENCY,
    InvalidSchema,
    MemorySearchRequest,
    MemoryStoreRequest,
    RegisterAgentRequest,
    TaskSubmitRequest,
    TaskSubmitResponse,
)
from .versioning import ApiVersion, InvalidApiVersion, parse_request_version

__all__ = [
    "AgentsListResponse",
    "ApiVersion",
    "AuthenticationError",
    "InvalidApiVersion",
    "InvalidSchema",
    "MUTATING_ENDPOINTS_REQUIRE_IDEMPOTENCY",
    "MemorySearchRequest",
    "MemoryStoreRequest",
    "Principal",
    "RegisterAgentRequest",
    "TaskSubmitRequest",
    "TaskSubmitResponse",
    "authenticate_bearer",
    "enforce_tenant_boundary",
    "parse_request_version",
]