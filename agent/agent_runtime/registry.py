"""Immutable definitions and an explicit implementation registry."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable

from .exceptions import AgentContractError
from .permissions import AgentPermissions

_MAX_TEXT_LENGTH = 65_536
_MAX_CAPABILITIES = 256
_IMPLEMENTATION_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def _require_identity(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AgentContractError(f"{name} must be a non-empty string")
    if len(value) > _MAX_TEXT_LENGTH:
        raise AgentContractError(f"{name} exceeds the {_MAX_TEXT_LENGTH}-character limit")


def _require_implementation_id(value: object) -> None:
    if not isinstance(value, str) or _IMPLEMENTATION_ID.fullmatch(value) is None:
        raise AgentContractError("implementation_id has invalid syntax")


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    agent_id: str
    version: int
    name: str
    role: str
    implementation_id: str
    capabilities: tuple[str, ...]
    trust_score: float
    permissions: AgentPermissions

    def __post_init__(self) -> None:
        for name in ("agent_id", "name", "role"):
            _require_identity(name, getattr(self, name))
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise AgentContractError("version must be a positive integer")
        _require_implementation_id(self.implementation_id)
        if (
            not isinstance(self.capabilities, tuple)
            or not self.capabilities
            or len(self.capabilities) > _MAX_CAPABILITIES
        ):
            raise AgentContractError("capabilities must be a non-empty bounded tuple")
        for capability in self.capabilities:
            _require_identity("capability", capability)
        if len(set(self.capabilities)) != len(self.capabilities):
            raise AgentContractError("capabilities must be unique")
        try:
            normalized_trust_score = float(self.trust_score)
        except (OverflowError, TypeError, ValueError):
            normalized_trust_score = math.nan
        if (
            isinstance(self.trust_score, bool)
            or not isinstance(self.trust_score, (int, float))
            or not math.isfinite(normalized_trust_score)
            or not 0 <= normalized_trust_score <= 1
        ):
            raise AgentContractError("trust_score must be finite and between 0 and 1")
        if type(self.permissions) is not AgentPermissions:
            raise AgentContractError("permissions must be an exact AgentPermissions value")
        permissions = self.permissions
        object.__setattr__(self, "agent_id", str(self.agent_id))
        object.__setattr__(self, "version", int(self.version))
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "role", str(self.role))
        object.__setattr__(self, "implementation_id", str(self.implementation_id))
        object.__setattr__(
            self,
            "capabilities",
            tuple(str(capability) for capability in self.capabilities),
        )
        object.__setattr__(self, "trust_score", normalized_trust_score)
        object.__setattr__(
            self,
            "permissions",
            AgentPermissions(
                read_files=permissions.read_files,
                write_files=permissions.write_files,
                execute_code=permissions.execute_code,
                network_access=permissions.network_access,
                memory_read=permissions.memory_read,
                memory_write=permissions.memory_write,
                agent_message_send=permissions.agent_message_send,
            ),
        )

    @property
    def key(self) -> tuple[str, int]:
        return (self.agent_id, self.version)


class AgentRegistry:
    __slots__ = ("__allowed_implementation_ids", "__definitions")

    def __init__(self, allowed_implementation_ids: Iterable[str]) -> None:
        if isinstance(allowed_implementation_ids, (str, bytes)):
            raise AgentContractError("allowed_implementation_ids must be an iterable of identifiers")
        try:
            supplied_ids = tuple(allowed_implementation_ids)
        except TypeError as exc:
            raise AgentContractError(
                "allowed_implementation_ids must be an iterable of identifiers"
            ) from exc
        for implementation_id in supplied_ids:
            _require_implementation_id(implementation_id)
        self.__allowed_implementation_ids = frozenset(
            str(implementation_id) for implementation_id in supplied_ids
        )
        self.__definitions: dict[tuple[str, int], AgentDefinition] = {}

    @staticmethod
    def __copy_definition(definition: AgentDefinition) -> AgentDefinition:
        permissions = definition.permissions
        copied_permissions = AgentPermissions(
            read_files=permissions.read_files,
            write_files=permissions.write_files,
            execute_code=permissions.execute_code,
            network_access=permissions.network_access,
            memory_read=permissions.memory_read,
            memory_write=permissions.memory_write,
            agent_message_send=permissions.agent_message_send,
        )
        return AgentDefinition(
            agent_id=definition.agent_id,
            version=definition.version,
            name=definition.name,
            role=definition.role,
            implementation_id=definition.implementation_id,
            capabilities=tuple(item for item in definition.capabilities),
            trust_score=definition.trust_score,
            permissions=copied_permissions,
        )

    def register(self, definition: AgentDefinition) -> AgentDefinition:
        if type(definition) is not AgentDefinition:
            raise AgentContractError("definition must be an exact AgentDefinition value")
        copied_definition = self.__copy_definition(definition)
        if copied_definition.implementation_id not in self.__allowed_implementation_ids:
            raise AgentContractError("implementation_id is not allowlisted")
        versions = [
            version
            for agent_id, version in self.__definitions
            if agent_id == copied_definition.agent_id
        ]
        expected_version = max(versions, default=0) + 1
        if copied_definition.version != expected_version:
            raise AgentContractError(f"version must be exactly {expected_version}")
        self.__definitions[copied_definition.key] = copied_definition
        return self.__copy_definition(copied_definition)

    def get(self, agent_id: str, version: int) -> AgentDefinition:
        _require_identity("agent_id", agent_id)
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise AgentContractError("version must be a positive integer")
        return self.__copy_definition(self.__definitions[(agent_id, version)])

    def latest(self, agent_id: str) -> AgentDefinition:
        _require_identity("agent_id", agent_id)
        matching = [
            definition
            for (registered_id, _), definition in self.__definitions.items()
            if registered_id == agent_id
        ]
        if not matching:
            raise KeyError(agent_id)
        return self.__copy_definition(max(matching, key=lambda definition: definition.version))

    def list(self) -> tuple[AgentDefinition, ...]:
        return tuple(
            self.__copy_definition(self.__definitions[key])
            for key in sorted(self.__definitions)
        )

    def snapshot(self) -> tuple[AgentDefinition, ...]:
        return self.list()
