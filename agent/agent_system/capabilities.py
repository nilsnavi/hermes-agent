"""Declarative capability surface for system agents.

A declared capability is METADATA and never an execution grant. Stating that an
agent "is declared for" X confers zero authority to do X in the world; the only
authority to touch anything comes from the verified execution kernel further
down the stack. Therefore this module holds ONLY declarations (data) and exposes
NO grant/authorize/execute/dispatch surface anywhere. A `CapabilitySurface`
describes what an agent is declared for; it cannot be used to request, permit,
or dispatch execution.

This is the "Agent capability declaration (descriptive only)" scope item.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .exceptions import CapabilityDeclarationError

_MAX_TEXT_LENGTH = 65_536
_MAX_DECLARATIONS = 256


def _require_bounded_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityDeclarationError(f"{name} must be a non-empty string")
    if len(value) > _MAX_TEXT_LENGTH:
        raise CapabilityDeclarationError(
            f"{name} exceeds the {_MAX_TEXT_LENGTH}-character limit"
        )
    return value


class SystemCapability(Enum):
    """Canonical, declarative capability vocabulary of the system-agent layer.

    These tokens describe what a system agent is *declared* to offer. The
    presence of a token is never permission and never the ability to execute.
    """

    PLANNING = "planning"
    RESEARCH = "research"
    CODING_EXECUTION = "coding_execution"
    REVIEW = "review"
    MEMORY_PROPOSAL = "memory_proposal"
    COORDINATION = "coordination"
    MONITORING_OBSERVATION = "monitoring_observation"


# Sentinel: the immutable canonical set, used for fail-closed membership checks.
CANONICAL_CAPABILITIES = frozenset(SystemCapability)


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    """One immutable, descriptive capability annotation for a system agent."""

    agent_id: str
    capability: SystemCapability
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_id", _require_bounded_text("agent_id", self.agent_id))
        if type(self.capability) is not SystemCapability:
            raise CapabilityDeclarationError(
                "capability must be an exact SystemCapability value"
            )
        object.__setattr__(
            self, "description", _require_bounded_text("description", self.description)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "capability": self.capability.value,
            "description": self.description,
        }


class CapabilitySurface:
    """The declared, descriptive capability set for exactly one system agent.

    This is pure data: it describes WHAT an agent is declared for and grants
    NOTHING. There is deliberately no method here that turns a declaration into
    permission, an execution request, or a dispatch. The only operations are
    read-only inspection for the control plane.
    """

    __slots__ = ("_agent_id", "_by_value", "_declarations")

    def __init__(self, declarations: tuple[CapabilityDeclaration, ...]) -> None:
        if not isinstance(declarations, tuple):
            raise CapabilityDeclarationError("declarations must be a tuple")
        if not declarations:
            raise CapabilityDeclarationError("declarations must not be empty")
        if len(declarations) > _MAX_DECLARATIONS:
            raise CapabilityDeclarationError("too many declarations")
        for item in declarations:
            if type(item) is not CapabilityDeclaration:
                raise CapabilityDeclarationError(
                    "declarations must hold exact CapabilityDeclaration values"
                )
        _agent_id = declarations[0].agent_id
        if any(item.agent_id != _agent_id for item in declarations):
            raise CapabilityDeclarationError(
                "all declarations in a surface must share one agent_id"
            )
        seen: dict[SystemCapability, CapabilityDeclaration] = {}
        for item in declarations:
            if item.capability in seen:
                raise CapabilityDeclarationError(
                    f"duplicate capability declaration: {item.capability.value}"
                )
            seen[item.capability] = item
        self._agent_id = _agent_id
        self._by_value: dict[SystemCapability, CapabilityDeclaration] = seen
        self._declarations: tuple[CapabilityDeclaration, ...] = declarations

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def declared(self) -> tuple[SystemCapability, ...]:
        """The declared capability values (descriptive only)."""
        return tuple(self._by_value.keys())

    def declaration(self, capability: SystemCapability) -> CapabilityDeclaration | None:
        """Return the declaration for a capability, or None if not declared."""
        if type(capability) is not SystemCapability:
            raise CapabilityDeclarationError(
                "capability must be an exact SystemCapability value"
            )
        return self._by_value.get(capability)

    def contains(self, capability: SystemCapability) -> bool:
        if type(capability) is not SystemCapability:
            raise CapabilityDeclarationError(
                "capability must be an exact SystemCapability value"
            )
        return capability in self._by_value

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self._agent_id,
            "capabilities": [item.capability.value for item in self._declarations],
        }


def declare_capabilities(
    agent_id: str,
    *,
    capabilities: tuple[SystemCapability, ...],
    description: str,
) -> CapabilitySurface:
    """Build a descriptive capability surface for one system agent.

    This constructs DATA only. It does not register the agent, does not touch
    permissions, and confers no authority whatsoever.
    """
    _require_bounded_text("agent_id", agent_id)
    if not isinstance(capabilities, tuple) or not capabilities:
        raise CapabilityDeclarationError("capabilities must be a non-empty tuple")
    if len(set(capabilities)) != len(capabilities):
        raise CapabilityDeclarationError("capabilities must be unique")
    declarations = tuple(
        CapabilityDeclaration(
            agent_id=agent_id,
            capability=capability,
            description=description,
        )
        for capability in capabilities
    )
    return CapabilitySurface(declarations)


__all__ = [
    "CANONICAL_CAPABILITIES",
    "CapabilityDeclaration",
    "CapabilitySurface",
    "SystemCapability",
    "declare_capabilities",
    "validated_fields",
]