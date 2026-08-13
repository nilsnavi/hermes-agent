"""Persistence layer exceptions (Sprint 1.0.3)."""

from agent.execution.exceptions import (
    ConcurrentUpdateError,  # re-export — single source of truth
    ExecutionErrorBase,
)


class PersistenceErrorBase(ExecutionErrorBase):
    """Base class for all persistence-layer errors."""


__all__ = ["PersistenceErrorBase", "ConcurrentUpdateError"]
