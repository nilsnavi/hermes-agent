"""First system agent definitions for the Hermes 2.0 control plane.

These are DESCRIPTIVE definitions only -- the five MVP system agents announced
in the architecture (PlannerAgent, ResearchAgent, CodingAgent, ReviewerAgent,
MemoryAgent). Each is an immutable ``AgentDefinition`` (metadata): a role, a set
of declarative capability tokens, a trust signal and a minimal permission field.

A definition is NOT a grant and NOT a process. It carries no Python import path,
no executable, and no execution surface. Its ``capabilities`` and ``permissions``
are metadata that the control plane routes on; they confer zero ability to run a
tool. CodingAgent mutation (write_files/execute_code) stays OFF this phase and
cannot be re-enabled by this layer -- that requires the verified-executor +
sandbox composition gate described in the architecture security section.
"""

from __future__ import annotations

from enum import Enum

from agent.agent_runtime.permissions import AgentPermissions
from agent.agent_runtime.registry import AgentDefinition

from .capabilities import SystemCapability


class SystemAgentRole(Enum):
    PLANNER = "planner"
    RESEARCH = "research"
    CODING = "coding"
    REVIEWER = "reviewer"
    MEMORY = "memory"
    MONITORING = "monitoring"


# Canonical per-role declarative capabilities (values of SystemCapability).
_ROOT_CAPABILITIES: dict[SystemAgentRole, tuple[SystemCapability, ...]] = {
    SystemAgentRole.PLANNER: (SystemCapability.PLANNING, SystemCapability.COORDINATION),
    SystemAgentRole.RESEARCH: (SystemCapability.RESEARCH,),
    SystemAgentRole.CODING: (SystemCapability.CODING_EXECUTION,),
    SystemAgentRole.REVIEWER: (SystemCapability.REVIEW,),
    SystemAgentRole.MEMORY: (SystemCapability.MEMORY_PROPOSAL,),
    SystemAgentRole.MONITORING: (SystemCapability.MONITORING_OBSERVATION,),
}


def _agent_id(role: SystemAgentRole) -> str:
    return role.value


def _role_name(role: SystemAgentRole) -> str:
    return {
        SystemAgentRole.PLANNER: "Planner Agent",
        SystemAgentRole.RESEARCH: "Research Agent",
        SystemAgentRole.CODING: "Coding Agent",
        SystemAgentRole.REVIEWER: "Reviewer Agent",
        SystemAgentRole.MEMORY: "Memory Agent",
        SystemAgentRole.MONITORING: "Monitoring Agent",
    }[role]


# Implementation ids are the only values the runtime registry may admit, and they
# cannot be created by registration -- they are fixed here and enforced by the
# registry allowlist. This is the "registry does not expand production
# capabilities" property.
SYSTEM_IMPLEMENTATION_IDS = frozenset(
    {
        "planner-agent",
        "research-agent",
        "coding-agent",
        "reviewer-agent",
        "memory-agent",
        "monitoring-agent",
    }
)


def _permissions(role: SystemAgentRole) -> AgentPermissions:
    # Conservative, default-deny metadata. CodingAgent mutation is intentionally
    # off (write_files/execute_code=False). Nothing here grants execution.
    if role is SystemAgentRole.PLANNER:
        return AgentPermissions(agent_message_send=True)
    if role is SystemAgentRole.RESEARCH:
        return AgentPermissions(read_files=True, agent_message_send=True)
    if role is SystemAgentRole.CODING:
        return AgentPermissions(read_files=True, agent_message_send=True)
    if role is SystemAgentRole.REVIEWER:
        return AgentPermissions(read_files=True, agent_message_send=True)
    if role is SystemAgentRole.MONITORING:
        return AgentPermissions(read_files=True, agent_message_send=True)  # read-only observation
    # Memory agent only proposes memory mutations; the controller writes.
    return AgentPermissions(memory_read=True, agent_message_send=True)


def _definition(role: SystemAgentRole) -> AgentDefinition:
    return AgentDefinition(
        agent_id=_agent_id(role),
        version=1,
        name=_role_name(role),
        role=role.value,
        implementation_id={
            SystemAgentRole.PLANNER: "planner-agent",
            SystemAgentRole.RESEARCH: "research-agent",
            SystemAgentRole.CODING: "coding-agent",
            SystemAgentRole.REVIEWER: "reviewer-agent",
            SystemAgentRole.MEMORY: "memory-agent",
            SystemAgentRole.MONITORING: "monitoring-agent",
        }[role],
        capabilities=tuple(cap.value for cap in _ROOT_CAPABILITIES[role]),
        trust_score={
            SystemAgentRole.PLANNER: 0.7,
            SystemAgentRole.RESEARCH: 0.8,
            SystemAgentRole.CODING: 0.75,
            SystemAgentRole.REVIEWER: 0.8,
            SystemAgentRole.MEMORY: 0.7,
            SystemAgentRole.MONITORING: 0.7,
        }[role],
        permissions=_permissions(role),
    )


def build_system_agent_definitions() -> tuple[AgentDefinition, ...]:
    """Return the six MVP system-agent definitions (one per role)."""
    return tuple(_definition(role) for role in SystemAgentRole)


def system_agent_definition(role: SystemAgentRole) -> AgentDefinition:
    """Return the definition for a single system-agent role."""
    if type(role) is not SystemAgentRole:
        raise ValueError("role must be an exact SystemAgentRole value")
    return _definition(role)


def system_agent_role(value: str) -> SystemAgentRole:
    """Map a role string to the enum; raises ValueError on unknown role."""
    return SystemAgentRole(value)


__all__ = [
    "SYSTEM_IMPLEMENTATION_IDS",
    "SystemAgentRole",
    "build_system_agent_definitions",
    "system_agent_definition",
    "system_agent_role",
]