"""Closed-world capability operation registry."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from agent.platform_policy.capability import CapabilityRequest

from .context import TrustedSurface
from .errors import (
    RegistryConfigurationError,
    RegistryFrozen,
    UnknownCapability,
)


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    operation: str
    platform_capability: str
    allowed_surfaces: frozenset[TrustedSurface]
    integration: str
    action: str
    required_secrets: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise RegistryConfigurationError(
                "operation must be a non-empty string"
            )

        # Reuse the canonical capability vocabulary. Construction fails closed
        # for unknown capability names.
        CapabilityRequest(self.platform_capability)

        if not self.allowed_surfaces:
            raise RegistryConfigurationError(
                "allowed_surfaces must not be empty"
            )
        for surface in self.allowed_surfaces:
            if type(surface) is not TrustedSurface:
                raise RegistryConfigurationError(
                    "allowed_surfaces contains non-trusted surface"
                )

        if not isinstance(self.integration, str) or not self.integration:
            raise RegistryConfigurationError(
                "integration must be a non-empty string"
            )
        if not isinstance(self.action, str) or not self.action:
            raise RegistryConfigurationError(
                "action must be a non-empty string"
            )

        for name in self.required_secrets:
            if not isinstance(name, str) or not name.strip():
                raise RegistryConfigurationError(
                    "required secret names must be non-empty strings"
                )


class CapabilityRegistry:
    """Trusted explicit registry with freeze-before-use semantics."""

    def __init__(self) -> None:
        self._definitions: dict[str, CapabilityDefinition] = {}
        self._frozen = False
        self._snapshot: Mapping[str, CapabilityDefinition] | None = None

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, definition: CapabilityDefinition) -> None:
        if self._frozen:
            raise RegistryFrozen("registry is frozen")
        if type(definition) is not CapabilityDefinition:
            raise RegistryConfigurationError(
                "definition must be an exact CapabilityDefinition"
            )
        if definition.operation in self._definitions:
            raise RegistryConfigurationError(
                f"duplicate capability operation {definition.operation!r}"
            )
        self._definitions[definition.operation] = definition

    def freeze(self) -> None:
        if self._frozen:
            return
        self._snapshot = MappingProxyType(dict(self._definitions))
        self._frozen = True

    def resolve(self, operation: str) -> CapabilityDefinition:
        if not self._frozen or self._snapshot is None:
            raise RegistryConfigurationError(
                "registry must be frozen before runtime resolution"
            )
        try:
            return self._snapshot[operation]
        except KeyError as exc:
            raise UnknownCapability(
                "operation is not registered"
            ) from exc

    def operations(self) -> frozenset[str]:
        if not self._frozen or self._snapshot is None:
            raise RegistryConfigurationError(
                "registry must be frozen before inspection"
            )
        return frozenset(self._snapshot)
