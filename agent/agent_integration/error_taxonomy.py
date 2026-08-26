"""Typed outcome taxonomy (Phase 6 §25).

Replaces generic boolean success with a closed, typed vocabulary of outcomes an
agent run may end in. An outcome is a control-plane classification token, never
a grant and never an execution authority.
"""

from __future__ import annotations

from enum import Enum


class AgentOutcome(Enum):
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED_SAFE = "agent_failed_safe"
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_UNKNOWN = "agent_unknown"
    AGENT_HUMAN_REVIEW = "agent_human_review"
    NO_ROUTE = "no_route"
    POLICY_DENIED = "policy_denied"
    BOUNDARY_DENIED = "boundary_denied"
    MEMORY_DENIED = "memory_denied"
    REGISTRY_DRIFT = "registry_drift"


# Outcomes that are NOT terminal-success and must be surfaced as failures.
NON_SUCCESS_OUTCOMES = frozenset(
    {
        AgentOutcome.AGENT_FAILED_SAFE,
        AgentOutcome.AGENT_TIMEOUT,
        AgentOutcome.AGENT_UNKNOWN,
        AgentOutcome.AGENT_HUMAN_REVIEW,
        AgentOutcome.NO_ROUTE,
        AgentOutcome.POLICY_DENIED,
        AgentOutcome.BOUNDARY_DENIED,
        AgentOutcome.MEMORY_DENIED,
        AgentOutcome.REGISTRY_DRIFT,
    }
)

# Outcomes that must NEVER feed an automatic retry of the SAME agent.
NO_AUTO_RETRY_OUTCOMES = frozenset(
    {
        AgentOutcome.AGENT_UNKNOWN,
        AgentOutcome.AGENT_TIMEOUT,
        AgentOutcome.AGENT_HUMAN_REVIEW,
        AgentOutcome.POLICY_DENIED,
        AgentOutcome.BOUNDARY_DENIED,
        AgentOutcome.MEMORY_DENIED,
        AgentOutcome.REGISTRY_DRIFT,
    }
)


__all__ = [
    "NON_SUCCESS_OUTCOMES",
    "NO_AUTO_RETRY_OUTCOMES",
    "AgentOutcome",
]