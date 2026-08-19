"""Sprint 1.3.11 — immutable profile + admission gate + static registry."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Blast, Class, Consumer, Criticality, Op

MAX_REGISTERED = 3

DENIED_CLASSES = {Class.CORE, Class.DATASTORE, Class.SCHEDULER, Class.PROVIDER,
                  Class.NETWORK, Class.SECURITY, Class.EXTERNAL, Class.UNKNOWN}
ALLOWED_CONSUMERS = {Consumer.NONE, Consumer.PASSIVE}
ALLOWED_BLAST = {Blast.NONE, Blast.SERVICE}


@dataclass(frozen=True)
class ReloadServiceProfile:
    service_id: str
    profile_version: int
    unit_name: str
    service_class: Class
    criticality: Criticality
    expected_user: str
    expected_executable: str
    expected_exec_reload: str
    blast_radius_ceiling: Blast
    risk_class: str = "MEDIUM_MUTATION"
    consumer: Consumer = Consumer.NONE
    config_validator_id: str = "json_schema"
    health_contract_id: str = "default"
    rollback_strategy: str = "reload_previous_config"
    enabled: bool = False
    created_at: str = ""


def admit(p: ReloadServiceProfile) -> str | None:
    """Return error reason or None if admitted."""
    if p.service_class in DENIED_CLASSES:
        return "SERVICE_CLASS_DENIED"
    if p.service_class is not Class.AUXILIARY:
        return "NOT_AUXILIARY"
    if p.criticality not in (Criticality.LOW, Criticality.MEDIUM):
        return "CRITICALITY_TOO_HIGH"
    if p.blast_radius_ceiling not in ALLOWED_BLAST:
        return "BLAST_RADIUS_TOO_HIGH"
    if p.consumer not in ALLOWED_CONSUMERS:
        return "CONSUMER_NOT_ALLOWED"
    if not p.expected_exec_reload:
        return "NO_EXECRELOAD"
    return None


@dataclass(frozen=True)
class AdmissionCheck:
    identity_verified: bool = True
    graph_healthy: bool = True
    critical_dependents: int = 0
    validator_exists: bool = True
    health_contact_exists: bool = True
    rollback_proven: bool = True


def full_admit(p: ReloadServiceProfile, chk: AdmissionCheck) -> str | None:
    r = admit(p)
    if r:
        return r
    if not chk.identity_verified:
        return "IDENTITY_UNVERIFIED"
    if not chk.graph_healthy:
        return "GRAPH_UNHEALTHY"
    if chk.critical_dependents > 0:
        return "CRITICAL_DEPENDENTS"
    if not chk.validator_exists:
        return "VALIDATOR_MISSING"
    if not chk.health_contact_exists:
        return "HEALTH_CONTRACT_MISSING"
    if not chk.rollback_proven:
        return "ROLLBACK_UNPROVEN"
    return None


class ReloadRegistry:
    """Small static registry; runtime discovery never grants authority."""

    def __init__(self):
        self._p: dict[str, ReloadServiceProfile] = {}

    def register(self, p: ReloadServiceProfile) -> None:
        if len(self._p) >= MAX_REGISTERED:
            raise RuntimeError("MAX_REGISTERED_RELOAD_SERVICES reached")
        self._p[p.service_id] = p

    def get(self, sid: str):
        return self._p.get(sid)

    def enabled(self, sid: str):
        p = self._p.get(sid)
        return p is not None and p.enabled