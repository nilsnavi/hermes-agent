"""Execution verifier (Sprint 1.0.2).

Post-tool checks: result exists, status is success, output was not lost,
required fields are filled. Returns the list of violated checks; an empty
list means the step passed verification.
"""

from typing import List

from .models import ExecutionStep
from .tool_runtime import ToolResult


class ExecutionVerifier:
    def verify(self, step: ExecutionStep, result: ToolResult) -> bool:
        """True iff *result* satisfies every check for *step*."""
        return not self.issues(step, result)

    def issues(self, step: ExecutionStep, result: ToolResult) -> List[str]:
        problems: List[str] = []
        if result is None:
            problems.append("result is missing")
            return problems
        if not step.tool:
            problems.append("step has no tool")
        if result.status != "success":
            problems.append(f"result status is '{result.status}', expected 'success'")
        if result.output is None or result.output == {}:
            problems.append("tool output is missing (execution lost)")
        if result.execution_time < 0:
            problems.append("negative execution time")
        return problems
