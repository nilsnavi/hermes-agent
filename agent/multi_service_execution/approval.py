"""Sprint 1.3.17 — approval binding validation (§17).

Global approval cannot replace child approvals.  Required: a global approval +
each child approval, each bound to the full execution context.  Any drift makes
the approval invalid.
"""
from __future__ import annotations

from collections.abc import Mapping

from .models import MultiServiceExecutionPlan


def approval_binding_valid(
    plan: MultiServiceExecutionPlan,
    *,
    global_approval_id: str,
    child_approvals: Mapping[str, str],
    approval_binding: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """Validate the global + per-child approval binding for one plan."""
    if not global_approval_id:
        return False, "missing-global-approval"
    for sid in plan.service_set:
        if sid not in child_approvals:
            return False, f"missing-child-approval:{sid}"
        # each child must reference the approval that was issued for it
        binding = approval_binding or {}
        expected = binding.get(sid, "")
        if expected and child_approvals[sid] != expected:
            return False, f"child-approval-drift:{sid}"
    return True, "approval-bound"


def approval_ttl_valid(plan: MultiServiceExecutionPlan, approval_ttl_until: float,
                       now_monotonic: float) -> bool:
    return approval_ttl_until > now_monotonic


__all__ = ["approval_binding_valid", "approval_ttl_valid"]