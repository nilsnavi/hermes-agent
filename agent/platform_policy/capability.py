"""Capability request models.

A capability request is a typed, bounded expression of what an agent wishes to
do. It carries the permission that must be explicitly granted and the capability
family it belongs to. A capability request is not authority: satisfying it only
proves the requester holds the corresponding permission; actual execution still
flows through the verified execution kernel, never from this model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet

from .exceptions import InvalidPermission
from .permissions import CANONICAL_PERMISSIONS, CAPABILITY_PERMISSION_ROLE


# Canonical capability families. A request must name a known family.
CANONICAL_CAPABILITIES: frozenset[str] = frozenset(
    {
        "task_analysis",
        "planning",
        "file_read",
        "file_write",
        "code_execution",
        "network_access",
        "memory_retrieval",
        "memory_mutation",
        "message_exchange",
        "validation",
        "supervision",
    }
)

# Each capability maps to exactly one required permission. A write/mutation
# capability must never resolve to a read-only permission, and vice versa.
CAPABILITY_TO_PERMISSION: dict[str, str] = {
    "task_analysis": "tasks.read",
    "planning": "tasks.submit",
    "file_read": "agents.read",
    "file_write": "agents.register",
    "code_execution": "system.operate",
    "network_access": "system.operate",
    "memory_retrieval": "memory.read",
    "memory_mutation": "memory.write",
    "message_exchange": "message.write",  # reserved; denied unless added to canonical
    "validation": "audit.read",
    "supervision": "tasks.cancel",
}

_MAX_CAPABILITIES = 64
_MAX_TEXT = 4096


def _require_bounded_str(name: object, label: str, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(name, str) or not name.strip():
        raise InvalidPermission(f"{label} must be a non-empty string")
    if len(name) > maximum:
        raise InvalidPermission(f"{label} exceeds {maximum} characters")
    return name


def _require_optional_bounded_str(
    name: object, label: str, maximum: int = _MAX_TEXT
) -> str:
    """Validate an optional bounded string: empty is allowed, otherwise non-empty."""
    if not isinstance(name, str):
        raise InvalidPermission(f"{label} must be a string")
    if not name:
        return ""
    if len(name) > maximum:
        raise InvalidPermission(f"{label} exceeds {maximum} characters")
    return name


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    capability: str
    reason: str = ""
    requested_resource: str = ""
    scope_ref: str = ""

    def __post_init__(self) -> None:
        if self.capability not in CANONICAL_CAPABILITIES:
            raise InvalidPermission(f"unknown capability {self.capability!r}")
        object.__setattr__(self, "reason", _require_optional_bounded_str(self.reason, "reason"))
        object.__setattr__(
            self,
            "requested_resource",
            _require_optional_bounded_str(self.requested_resource, "requested_resource"),
        )
        object.__setattr__(
            self, "scope_ref", _require_optional_bounded_str(self.scope_ref, "scope_ref")
        )

    @property
    def required_permission(self) -> str:
        # The mapping may resolve to a reserved, non-canonical permission
        # (e.g. message_exchange -> message.write). Such a target is NEVER
        # grantable because PermissionGrant rejects non-canonical names, so
        # the deny-by-default engine always denies it. Fail-closed by design.
        return CAPABILITY_TO_PERMISSION[self.capability]


@dataclass(frozen=True, slots=True)
class CapabilityRequestSet:
    requests: AbstractSet[CapabilityRequest] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.requests, set) and not isinstance(
            self.requests, frozenset
        ):
            raise InvalidPermission("requests must be a set of CapabilityRequest")
        if len(self.requests) > _MAX_CAPABILITIES:
            raise InvalidPermission("requests exceeds the 64-item limit")
        checked: set[CapabilityRequest] = set()
        for request in self.requests:
            if type(request) is not CapabilityRequest:
                raise InvalidPermission(
                    "requests must contain only exact CapabilityRequest values"
                )
            checked.add(request)
        object.__setattr__(self, "requests", frozenset(checked))