"""Plan validation (Sprint 1.0.5).

Every plan is validated BEFORE any tool call: unique step ids, known
tools (registered), TaskContext allowlist, argument shape. Validation
issues → INVALID_PLAN stop with ZERO tool executions.

The ExecutionPlanner already checks shape + allowlist and raises
InvalidPlan; this validator adds the registry check and the duplicate-id
check on the BUILT plan.
"""

from typing import List, Optional

from agent.execution.models import ExecutionPlan, ExecutionStep
from agent.execution.registry import ToolRegistry
from agent.runtime.context import TaskContext


class PlanValidator:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def validate(
        self,
        plan: ExecutionPlan,
        context: Optional[TaskContext] = None,
    ) -> List[str]:
        """Return the list of issues; empty list = plan is executable."""
        issues: List[str] = []
        if not plan.steps:
            issues.append("plan has no steps")
        seen: set = set()
        for index, step in enumerate(plan.steps):
            if step.id in seen:
                issues.append(f"duplicate step id: {step.id}")
            seen.add(step.id)
            if not self._registry.has(step.tool):
                issues.append(f"step {step.id}: unknown tool '{step.tool}'")
            if context is not None and context.allowed_tools and step.tool not in context.allowed_tools:
                issues.append(
                    f"step {step.id}: tool '{step.tool}' not in allowed_tools"
                )
            if not isinstance(step.arguments, dict):
                issues.append(f"step {step.id}: arguments must be a dict")
        return issues

    def is_valid(self, plan: ExecutionPlan, context: Optional[TaskContext] = None) -> bool:
        return not self.validate(plan, context)
