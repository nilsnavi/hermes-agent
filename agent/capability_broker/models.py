"""Capability Broker request/response models.

Operation payloads carry business intent only. Identity, tenant, permissions,
tokens, URLs, headers, and HTTP methods are intentionally absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .errors import InvalidCapabilityRequest


_MAX_OPERATION = 160
_MAX_ARGUMENTS = 32
_MAX_REQUEST_ID = 256


class CapabilityResult(str, Enum):
    SUCCESS = "success"
    DENIED = "denied"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class CapabilityOperationRequest:
    operation: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise InvalidCapabilityRequest(
                "operation must be a non-empty string"
            )
        operation = self.operation.strip()
        if len(operation) > _MAX_OPERATION:
            raise InvalidCapabilityRequest(
                f"operation exceeds {_MAX_OPERATION} characters"
            )

        if not isinstance(self.arguments, Mapping):
            raise InvalidCapabilityRequest("arguments must be a mapping")
        if len(self.arguments) > _MAX_ARGUMENTS:
            raise InvalidCapabilityRequest(
                f"arguments exceeds {_MAX_ARGUMENTS} items"
            )

        checked: dict[str, Any] = {}
        for key, value in self.arguments.items():
            if not isinstance(key, str) or not key.strip():
                raise InvalidCapabilityRequest(
                    "argument names must be non-empty strings"
                )
            checked[key] = value

        if not isinstance(self.request_id, str):
            raise InvalidCapabilityRequest("request_id must be a string")
        if len(self.request_id) > _MAX_REQUEST_ID:
            raise InvalidCapabilityRequest(
                f"request_id exceeds {_MAX_REQUEST_ID} characters"
            )

        object.__setattr__(self, "operation", operation)
        object.__setattr__(
            self,
            "arguments",
            MappingProxyType(checked),
        )

    def __getstate__(self) -> dict[str, Any]:
        # Explicitly documents the non-authoritative serialized surface.
        return {
            "operation": self.operation,
            "arguments": dict(self.arguments),
            "request_id": self.request_id,
        }


@dataclass(frozen=True, slots=True)
class CapabilityResponse:
    result: CapabilityResult
    data: Any = None
    reason_code: str = ""

    def __post_init__(self) -> None:
        if type(self.result) is not CapabilityResult:
            raise InvalidCapabilityRequest(
                "result must be an exact CapabilityResult"
            )
        if not isinstance(self.reason_code, str):
            raise InvalidCapabilityRequest("reason_code must be a string")
