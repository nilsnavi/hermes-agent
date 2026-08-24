"""Strict twenty-step restart admission and public mutation boundary."""
from __future__ import annotations

from .consumer import RestartConsumerPolicy
from .models import AdmissionContext, AdmissionDecision, BlastRadius
from .registry import RestartProfileRegistry

_GATEWAY_IDS = {"hermes-gateway", "hermes-gateway.service", "gateway"}
_ALLOWED_BLAST = {BlastRadius.RESOURCE, BlastRadius.SERVICE}


class RestartAdmission:
    """Apply the brief's exact fail-closed precedence; earliest failure wins."""

    PRECEDENCE = (
        "SELF_CONTROL_FORBIDDEN",
        "NOT_REGISTERED",
        "SERVICE_CLASS_DENIED",
        "IDENTITY_UNVERIFIED",
        "PROFILE_VERSION_MISMATCH",
        "GRAPH_UNHEALTHY",
        "CONSUMER_DENIED",
        "DEPENDENCY_DENIED",
        "BLAST_RADIUS_DENIED",
        "PRE_HEALTH_FAILED",
        "CONFIG_INVALID",
        "QUIESCENCE_UNPROVEN",
        "STARTUP_UNPROVEN",
        "RECOVERY_UNPROVEN",
        "RISK_DENIED",
        "APPROVAL_INVALID",
        "BUDGET_EXCEEDED",
        "BREAKER_OPEN",
        "LOCK_CONFLICT",
        "ROLLOUT_DISABLED",
    )

    def __init__(self, registry: RestartProfileRegistry) -> None:
        self.registry = registry
        self.consumer_policy = RestartConsumerPolicy()

    def decide(self, c: AdmissionContext) -> AdmissionDecision:
        if c.service_id in _GATEWAY_IDS:
            return AdmissionDecision(False, "SELF_CONTROL_FORBIDDEN", 1)
        if c.operation != "RESTART":
            return AdmissionDecision(False, "OPERATION_DENIED", 0)
        profile = self.registry.resolve(c.service_id)
        checks = (
            (False, "SELF_CONTROL_FORBIDDEN"),
            (profile is None, "NOT_REGISTERED"),
            (
                c.service_class != "HERMES_AUXILIARY"
                or c.criticality != "LOW"
                or not c.restart_supported
                or (profile is not None and not profile.restart_supported),
                "SERVICE_CLASS_DENIED",
            ),
            (
                not c.identity_verified
                or (
                    c.runtime_discovered_unit is not None
                    and profile is not None
                    and c.runtime_discovered_unit != profile.unit_name
                ),
                "IDENTITY_UNVERIFIED",
            ),
            (
                profile is not None and profile.profile_version != c.profile_version,
                "PROFILE_VERSION_MISMATCH",
            ),
            (not c.graph_healthy, "GRAPH_UNHEALTHY"),
            (not self.consumer_policy.allowed(c.consumer), "CONSUMER_DENIED"),
            (bool(c.dependents), "DEPENDENCY_DENIED"),
            (c.blast_radius not in _ALLOWED_BLAST, "BLAST_RADIUS_DENIED"),
            (not c.pre_health_ok or not c.health_contract_complete, "PRE_HEALTH_FAILED"),
            (not c.config_valid, "CONFIG_INVALID"),
            (not c.quiescence_proven, "QUIESCENCE_UNPROVEN"),
            (not c.startup_proven, "STARTUP_UNPROVEN"),
            (not c.rollback_proven, "RECOVERY_UNPROVEN"),
            (not c.risk_acceptable, "RISK_DENIED"),
            (not c.approval_valid, "APPROVAL_INVALID"),
            (not c.budget_available, "BUDGET_EXCEEDED"),
            (not c.breaker_closed, "BREAKER_OPEN"),
            (not c.lock_available, "LOCK_CONFLICT"),
            (not c.rollout_enabled, "ROLLOUT_DISABLED"),
        )
        for step, (failed, reason) in enumerate(checks, 1):
            if failed:
                return AdmissionDecision(False, reason, step)
        return AdmissionDecision(True, "ALLOW_EXACT_REGISTERED_PROFILE", 20)


class LimitedRestartPolicy:
    """Public safety facade. Only typed RESTART may reach admission."""

    def __init__(self, registry: RestartProfileRegistry | None = None) -> None:
        self.registry = registry or RestartProfileRegistry()
        self.admission = RestartAdmission(self.registry)

    def public_mutation(self, service_id: str, operation: str) -> AdmissionDecision:
        if service_id in _GATEWAY_IDS:
            return AdmissionDecision(False, "SELF_CONTROL_FORBIDDEN", 1)
        if operation != "RESTART":
            return AdmissionDecision(False, "OPERATION_DENIED", 0)
        return AdmissionDecision(False, "ROLLOUT_DISABLED", 20)


__all__ = ["LimitedRestartPolicy", "RestartAdmission"]
