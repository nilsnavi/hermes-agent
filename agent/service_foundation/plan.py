"""Sprint 1.3.9 — ServiceChangePlan + P0 execution guard (always DISABLED)."""
from __future__ import annotations

import hashlib

from .exceptions import ExecutionDisabled


def plan_fingerprint(plan) -> str:
    raw = (plan.service_id, plan.profile_version, plan.operation.value,
           plan.identity_fingerprint, plan.dependency_graph_digest,
           plan.risk.value, plan.blast_radius.value, plan.rollback_strategy)
    return hashlib.sha256(repr(raw).encode()).hexdigest()


def revalidate_required(new, old) -> bool:
    """Eligibility/plan must be revalidated if any binding changed."""
    return not (
        new.service_id == old.service_id
        and new.profile_version == old.profile_version
        and new.identity_fingerprint == old.identity_fingerprint
        and new.dependency_graph_digest == old.dependency_graph_digest
        and new.operation == old.operation
    )


def execute(plan) -> None:
    """P0: calling execute() on ANY plan is ALWAYS disabled in Sprint 1.3.9.

    Regardless of eligibility, this returns/raises SERVICE_MUTATION_DISABLED
    and performs zero mutation / adapter calls.
    """
    raise ExecutionDisabled("SERVICE_MUTATION_DISABLED: service mutation execution is not enabled (Sprint 1.3.9)")
