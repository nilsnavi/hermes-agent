"""Sprint 1.3.10 models: enums + immutable plan."""
import hashlib, time
from dataclasses import dataclass
from enum import Enum


class Mode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    CANARY = "canary"


class Outcome(str, Enum):
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    DENIED = "DENIED"


@dataclass(frozen=True)
class ServiceReloadPlan:
    transaction_id: str
    service_id: str
    unit_name: str
    profile_version: int
    operation: str            # RELOAD_ONE_REGISTERED_AUX_SERVICE
    identity_fingerprint: str
    graph_digest: str
    config_validation_receipt: str
    health_before_receipt: str
    approval_id: str
    risk: str
    blast_radius: str
    rollback_strategy: str
    created_at: float = time.time()
    expires_at: float = 0.0
    baseline_sha: str = "fc2c8939099795d425e627089479c7cdc374d7d0"
