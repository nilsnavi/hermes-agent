"""Task Analyzer.

The analyzer turns a user goal into a structured, deterministic signal used by
the Planner. It performs classification only: it never executes tools, never
selects agents, and never grants permission. Output is a compact analysis with
a required capabilities hint; the Planner is free to reject or refine it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet


class InvalidAnalysisInput(ValueError):
    """Raised when the analyzer receives malformed input."""


# Deterministic keyword families used for planner hinting. These are weak
# signals only; the Planner applies policy, not vocabulary, for authority.
_WRITE_HINTS = frozenset({"создай", "напиши", "измени", "обнови", "create", "write", "edit", "update"})
_MEMORY_HINTS = frozenset({"вспомни", "запомни", "память", "remember", "memory", "recall"})
_VERIFY_HINTS = frozenset({"проверь", "реценз", "verify", "review", "validate", "проверка"})


@dataclass(frozen=True, slots=True)
class TaskAnalysis:
    goal: str
    task_id: str
    suggested_capabilities: tuple[str, ...]
    read_only: bool
    requires_verification: bool

    def __post_init__(self) -> None:
        if not isinstance(self.goal, str) or not self.goal.strip():
            raise InvalidAnalysisInput("goal must be a non-empty string")
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise InvalidAnalysisInput("task_id must be a non-empty string")
        if not isinstance(self.suggested_capabilities, tuple):
            raise InvalidAnalysisInput("suggested_capabilities must be a tuple")


class TaskAnalyzer:
    """Deterministic, pure goal classifier. No I/O, no execution surface."""

    @staticmethod
    def analyze(goal: object, task_id: object) -> TaskAnalysis:
        if not isinstance(goal, str) or not goal.strip():
            raise InvalidAnalysisInput("goal must be a non-empty string")
        if not isinstance(task_id, str) or not task_id.strip():
            raise InvalidAnalysisInput("task_id must be a non-empty string")

        text = goal.lower()
        words = set(text.replace(",", " ").replace(".", " ").split())

        capabilities: list[str] = ["task_analysis"]
        if words & _WRITE_HINTS:
            capabilities.append("planning")
        if words & _MEMORY_HINTS:
            capabilities.append("memory_retrieval")
        if words & _VERIFY_HINTS:
            capabilities.append("validation")

        # read_only: no write/code/network hint present -> conservative read.
        write_signal = bool(words & _WRITE_HINTS)
        read_only = not write_signal

        return TaskAnalysis(
            goal=goal,
            task_id=task_id,
            suggested_capabilities=tuple(capabilities),
            read_only=read_only,
            requires_verification=bool(words & _VERIFY_HINTS),
        )