"""Immutable models for the simulation-only two-service canary."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from enum import Enum
from typing import Any

BASELINE_SHA = "672b5aadd1d6fab61274c2d8cba31b7174954b06"
CAPABILITY = "HERMES_MULTI_SERVICE_EXECUTION_CANARY"
OPERATION = "SIMULATE_TWO_REGISTERED_AUX_SERVICES"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class CanaryDecision(str, Enum):
    DENIED = "DENIED"
    CANARY_DISABLED = "CANARY_DISABLED"
    REVALIDATE_REQUIRED = "REVALIDATE_REQUIRED"
    GLOBAL_FAILED = "GLOBAL_FAILED"
    COMPENSATION_REQUIRED_SIMULATED = "COMPENSATION_REQUIRED_SIMULATED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    GLOBAL_COMMITTED_SIMULATED = "GLOBAL_COMMITTED_SIMULATED"


class SimulatedOutcome(str, Enum):
    SIMULATED_SUCCESS = "SIMULATED_SUCCESS"
    SIMULATED_FAILURE = "SIMULATED_FAILURE"
    SIMULATED_UNKNOWN = "SIMULATED_UNKNOWN"


@dataclasses.dataclass(frozen=True, slots=True)
class CanaryServiceProfile:
    service_id: str
    identity: str
    service_class: str = "HERMES_AUXILIARY"
    criticality: str = "LOW"
    blast: str = "SERVICE"
    fixture_kind: str = "NON_SYSTEMD_EXECUTION_FIXTURE"


@dataclasses.dataclass(frozen=True, slots=True)
class CanaryServiceSet:
    service_ids: tuple[str, ...]
    service_profiles: tuple[CanaryServiceProfile, ...]
    registry_digest: str
    graph_digest: str
    baseline_sha: str
    generation: int
    operation: str
    risk: str
    blast: str
    consumer_set: tuple[str, ...]
    created_monotonic: float
    expires_monotonic: float

    def semantic_hash(self) -> str:
        return _hash({"baseline": self.baseline_sha, "generation": self.generation,
                      "services": self.service_ids, "profiles": [dataclasses.asdict(p) for p in self.service_profiles],
                      "registry": self.registry_digest, "graph": self.graph_digest,
                      "operation": self.operation, "risk": self.risk, "blast": self.blast,
                      "consumers": self.consumer_set})


@dataclasses.dataclass(frozen=True, slots=True)
class ProductionCanaryRequest:
    request_id: str
    baseline_sha: str
    generation: int
    service_ids: tuple[str, ...]
    registry_digest: str
    graph_digest: str
    approval_id: str
    plan_hash: str
    operation: str
    risk: str
    blast: str
    created_monotonic: float
    expires_monotonic: float
    approval_binding: str = ""

    def expected_approval_binding(self) -> str:
        return _hash({"baseline": self.baseline_sha, "generation": self.generation,
                      "services": tuple(sorted(self.service_ids)), "registry": self.registry_digest,
                      "graph": self.graph_digest, "plan": self.plan_hash,
                      "operation": self.operation, "risk": self.risk, "blast": self.blast})

    @classmethod
    def for_exact_canary(cls, *, request_id: str, baseline_sha: str, generation: int,
                         approval_id: str, plan_hash: str, created_monotonic: float,
                         expires_monotonic: float) -> "ProductionCanaryRequest":
        from .registry import CanaryServiceRegistry
        r = CanaryServiceRegistry()
        value = cls(request_id, baseline_sha, generation, r.service_ids(), r.digest,
                    r.graph_digest, approval_id, plan_hash, OPERATION,
                    "MEDIUM_MUTATION_MODEL", "MULTI_SERVICE", created_monotonic,
                    expires_monotonic)
        return dataclasses.replace(value, approval_binding=value.expected_approval_binding())

    def semantic_key(self) -> str:
        return _hash({"baseline": self.baseline_sha, "generation": self.generation,
                      "services": tuple(sorted(self.service_ids)), "registry": self.registry_digest,
                      "graph": self.graph_digest, "plan": self.plan_hash,
                      "operation": self.operation, "risk": self.risk, "blast": self.blast})


@dataclasses.dataclass(frozen=True, slots=True)
class ChildExecutionIntent:
    service_id: str
    operation: str
    plan_hash: str
    expected_effect: str = "SIMULATED_EFFECT_ONLY"


@dataclasses.dataclass(frozen=True, slots=True)
class CanaryResult:
    decision: CanaryDecision
    adapter_call_count: int = 0
    replayed: bool = False
    real_global_commit: bool = False
    reason: str = ""
    child_outcomes: tuple[tuple[str, str], ...] = ()
    compensation_order: tuple[str, ...] = ()
