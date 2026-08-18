"""Sprint 1.3.8 — immutable resource profiles, typed operations, target registry."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .risk import BlastRadius, ConsumerClass, RiskClass


class Operation(str, Enum):
    """Typed operations only (no generic WRITE/MUTATE/EXECUTE)."""
    UPDATE_JSON = "update_json"
    REPLACE_TEXT = "replace_text"
    SET_MARKER = "set_marker"
    CREATE_MANAGED_ENTRY = "create_managed_entry"
    DELETE_MANAGED_ENTRY = "delete_managed_entry"


#: name validator for newly-created managed targets (§10)
TARGET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._\-]{0,63}$")
_RESERVED_NAMES = {"config.yaml", "state.db", ".env", "..", "."}
_FORBIDDEN_NAME_CHARS = set("\\/")  # no path separators inside a name
_CONTROL_OR_UNICODE = re.compile(r"[\x00-\x1f\x7f\u202e\u202d\u2066\u2067\u2068\u2069]")


def validate_target_name(name: str) -> str:
    if not TARGET_NAME_RE.match(name):
        raise ValueError(f"invalid target name: {name!r}")
    if name in _RESERVED_NAMES:
        raise ValueError(f"reserved target name: {name!r}")
    if _CONTROL_OR_UNICODE.search(name):
        raise ValueError(f"forbidden chars in target name: {name!r}")
    return name


@dataclass(frozen=True)
class MutationBudgetSpec:
    max_successful_per_hour: int = 3
    max_attempts_per_hour: int = 5
    max_rollbacks_per_hour: int = 3
    max_failures_per_hour: int = 5


@dataclass(frozen=True)
class ProductionResourceProfile:
    """Immutable, versioned resource authority. No silent mutation."""
    profile_id: str
    version: int
    resource_class: str
    capability: str
    allowed_operations: frozenset[Operation]
    risk_class: RiskClass
    consumer_class: ConsumerClass
    blast_radius_ceiling: BlastRadius
    exact_target_dir: str
    owner: str
    mode: int
    max_payload_size: int
    schema_validator: Any = None
    approval_required: bool = True
    snapshot_required: bool = True
    enabled: bool = False
    created_at: str = ""
    budget: MutationBudgetSpec = field(default_factory=MutationBudgetSpec)

    @property
    def identity(self) -> str:
        return f"{self.profile_id}:{self.version}"

    def allow(self, op: Operation) -> bool:
        return op in self.allowed_operations


@dataclass(frozen=True)
class TargetRegistration:
    profile_id: str
    target_id: str
    resolved_path: str
    realpath: str
    owner: str
    mode: int
    enabled: bool = True
    created_at: str = ""
