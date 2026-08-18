"""Sprint 1.3.9 — eligibility engine (strict precedence, fail-closed)."""
from __future__ import annotations

from .models import (BlastRadius, Eligibility, GraphStatus, IdentityResult,
                    Operation, SelfControlClass, ServiceClass)

_FUTURE_RESTART_TARGET = Operation.RESTART_ELIGIBILITY
_FUTURE_RELOAD_TARGET = Operation.RELOAD_ELIGIBILITY

_HARD_DENY_CLASSES = {ServiceClass.HERMES_CORE, ServiceClass.DATASTORE,
                      ServiceClass.SCHEDULER, ServiceClass.PROVIDER,
                      ServiceClass.NETWORK, ServiceClass.SECURITY,
                      ServiceClass.EXTERNAL, ServiceClass.UNKNOWN}


def evaluate(profile, identity, graph, operation, *, health_ok=False,
             validator_ok=False, rollback_proven=False, exec_operation=False,
             mode="shadow") -> Eligibility:
    """Return eligibility for a service operation (analysis only)."""
    # 1. self-control prohibition (P0) — strongest override
    if profile is not None and profile.self_control_class is SelfControlClass.SELF_CONTROL_FORBIDDEN:
        return Eligibility.SELF_CONTROL_FORBIDDEN
    if exec_operation:
        return Eligibility.POLICY_DENIED  # never run execution in 1.3.9
    if profile is None:
        return Eligibility.UNKNOWN
    # 2. service class hard deny (future autonomous execution)
    if profile.service_class in _HARD_DENY_CLASSES:
        return Eligibility.SERVICE_CLASS_DENIED
    # 3. identity verification
    if identity is not IdentityResult.VERIFIED:
        return Eligibility.IDENTITY_UNVERIFIED
    # 4. graph health
    gs = graph.status() if graph is not None else GraphStatus.UNAVAILABLE
    if gs in (GraphStatus.STALE, GraphStatus.UNAVAILABLE, GraphStatus.CORRUPT):
        return Eligibility.GRAPH_STALE
    # 5. operation support
    op = operation
    if op in (Operation.RELOAD_ELIGIBILITY, Operation.EXEC_RELOAD):
        if not profile.reload_supported:
            return Eligibility.OPERATION_UNSUPPORTED
    elif op in (_FUTURE_RESTART_TARGET, Operation.EXEC_RESTART):
        if not profile.restart_supported:
            return Eligibility.OPERATION_UNSUPPORTED
    # 6. config validator (for reload) / 7. health contract
    if op in (Operation.RELOAD_ELIGIBILITY, Operation.EXEC_RELOAD):
        if not profile.config_validator_id:
            return Eligibility.CONFIG_VALIDATOR_MISSING
        if not validator_ok:
            return Eligibility.CONFIG_VALIDATOR_MISSING
    if not profile.health_contract_id:
        return Eligibility.HEALTH_CONTRACT_MISSING
    if not health_ok:
        return Eligibility.HEALTH_CONTRACT_MISSING
    # 8. rollback proof
    if not rollback_proven:
        return Eligibility.ROLLBACK_UNPROVEN
    # 9. blast radius — static ceiling AND dynamic dependents
    if profile.blast_radius_ceiling is BlastRadius.NONE or profile.blast_radius_ceiling is BlastRadius.UNKNOWN:
        return Eligibility.BLAST_RADIUS_TOO_HIGH
    if graph is not None and graph.has_dependents(profile.service_id):
        return Eligibility.BLAST_RADIUS_TOO_HIGH
    # 10. criticality 11. risk 12. approval 13. rollout 14. future canary
    # Auxiliary low-risk, service-only blast, proven rollback -> future canary eligible
    if op is Operation.RELOAD_ELIGIBILITY:
        return Eligibility.ELIGIBLE_FOR_FUTURE_RELOAD_CANARY
    return Eligibility.ELIGIBLE_FOR_FUTURE_RESTART_CANARY
