"""Execution planner (Sprint 1.0.2).

Deterministic, NON-autonomous: the caller supplies explicit step definitions
(autonomous planning is a later sprint); the planner validates them against
the TaskContext (allowlist, shape), assigns ids and initial statuses, and
propagates the approval requirement.
"""

from typing import Any, Dict, List, Optional

from agent.runtime.context import TaskContext

from .events import Clock, utcnow
from .exceptions import InvalidPlan
from .models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus


class ExecutionPlanner:
    def __init__(self, clock: Optional[Clock] = None) -> None:
        self._clock = clock or utcnow

    def create_plan(
        self,
        run_id: str,
        context: TaskContext,
        steps: List[Dict[str, Any]],
        plan_id: Optional[str] = None,
    ) -> ExecutionPlan:
        """Build a validated ExecutionPlan from explicit step definitions.

        Each step dict: ``name`` (required), ``tool`` (required, must be in
        ``context.allowed_tools`` when the list is non-empty), ``description``,
        ``arguments`` (dict), ``requires_approval`` (bool). The first step
        starts READY, the rest PENDING.
        """
        if not steps:
            raise InvalidPlan("plan requires at least one step")

        built: List[ExecutionStep] = []
        for index, raw in enumerate(steps, start=1):
            name = raw.get("name")
            tool = raw.get("tool")
            if not isinstance(name, str) or not name.strip():
                raise InvalidPlan(f"step {index}: 'name' is required")
            if not isinstance(tool, str) or not tool.strip():
                raise InvalidPlan(f"step {index}: 'tool' is required")
            if context.allowed_tools and tool not in context.allowed_tools:
                raise InvalidPlan(
                    f"step {index}: tool '{tool}' is not in allowed_tools"
                )
            arguments = raw.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise InvalidPlan(f"step {index}: 'arguments' must be a dict")
            built.append(
                ExecutionStep(
                    id=f"step-{index}",
                    name=name,
                    description=str(raw.get("description", "")),
                    tool=tool,
                    arguments=dict(arguments),
                    requires_approval=bool(raw.get("requires_approval", False))
                    or context.approval_required,
                )
            )

        built[0].status = StepStatus.READY
        return ExecutionPlan(
            id=plan_id or f"plan-{run_id}-{self._clock().strftime('%H%M%S%f')}",
            run_id=run_id,
            goal=context.goal,
            steps=built,
            status=PlanStatus.CREATED,
            created_at=self._clock(),
        )
