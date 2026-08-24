"""Sprint 1.3.15 — multi-service coordination data model.

Immutable plan / subplan / transaction / compensation / permit structures.
Plans are frozen after creation: they are never mutated.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum


class CoordinatorState(Enum):
    """Global state machine.  Real EXECUTING does not exist in 1.3.15."""

    CREATED = "CREATED"
    PLANNED = "PLANNED"
    ELIGIBILITY_CHECKED = "ELIGIBILITY_CHECKED"
    LOCKS_ACQUIRED = "LOCKS_ACQUIRED"
    PREPARED = "PREPARED"
    BARRIER_READY = "BARRIER_READY"
    EXECUTION_READY = "EXECUTION_READY"
    SIMULATED_EXECUTING = "SIMULATED_EXECUTING"
    VERIFYING = "VERIFYING"
    COMMIT_READY = "COMMIT_READY"
    COMMITTED_SIMULATED = "COMMITTED_SIMULATED"

    # failure states
    DENIED = "DENIED"
    PREPARE_FAILED = "PREPARE_FAILED"
    LOCK_FAILED = "LOCK_FAILED"
    BARRIER_FAILED = "BARRIER_FAILED"
    CHILD_FAILED = "CHILD_FAILED"
    VERIFY_FAILED = "VERIFY_FAILED"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


TERMINAL_STATES = {
    CoordinatorState.COMMITTED_SIMULATED,
    CoordinatorState.DENIED,
    CoordinatorState.PREPARE_FAILED,
    CoordinatorState.LOCK_FAILED,
    CoordinatorState.BARRIER_FAILED,
    CoordinatorState.CHILD_FAILED,
    CoordinatorState.VERIFY_FAILED,
    CoordinatorState.COMPENSATION_REQUIRED,
    CoordinatorState.COMPENSATION_FAILED,
    CoordinatorState.UNKNOWN_OUTCOME,
    CoordinatorState.MANUAL_REVIEW_REQUIRED,
}

FAILURE_STATES = TERMINAL_STATES - {CoordinatorState.COMMITTED_SIMULATED}

# Explicit legal progress transitions in the happy-path machine.
_EDGES = {
    CoordinatorState.CREATED: {CoordinatorState.PLANNED, CoordinatorState.DENIED},
    CoordinatorState.PLANNED: {CoordinatorState.ELIGIBILITY_CHECKED, CoordinatorState.DENIED},
    CoordinatorState.ELIGIBILITY_CHECKED: {CoordinatorState.LOCKS_ACQUIRED, CoordinatorState.DENIED},
    CoordinatorState.LOCKS_ACQUIRED: {CoordinatorState.PREPARED, CoordinatorState.LOCK_FAILED},
    CoordinatorState.PREPARED: {CoordinatorState.BARRIER_READY, CoordinatorState.PREPARE_FAILED},
    CoordinatorState.BARRIER_READY: {CoordinatorState.EXECUTION_READY, CoordinatorState.BARRIER_FAILED},
    CoordinatorState.EXECUTION_READY: {CoordinatorState.SIMULATED_EXECUTING},
    CoordinatorState.SIMULATED_EXECUTING: {CoordinatorState.VERIFYING, CoordinatorState.CHILD_FAILED},
    CoordinatorState.VERIFYING: {CoordinatorState.COMMIT_READY, CoordinatorState.VERIFY_FAILED},
    CoordinatorState.COMMIT_READY: {CoordinatorState.COMMITTED_SIMULATED},
}
# Fail-closed edges available from every non-terminal state: any terminal
# FAILURE state is a reachable abort sink (DENIED, LOCK_FAILED, PREPARE_FAILED,
# BARRIER_FAILED, CHILD_FAILED, VERIFY_FAILED, COMPENSATION_*, UNKNOWN_OUTCOME,
# MANUAL_REVIEW_REQUIRED).  COMMITTED_SIMULATED is the ONLY success and is never
# a corridor target from a stray state.
_FAIL_CORRIDOR = TERMINAL_STATES - {CoordinatorState.COMMITTED_SIMULATED}
for _s in list(_EDGES):
    _EDGES[_s] = _EDGES[_s] | _FAIL_CORRIDOR
_EDGES = {k: frozenset(v) for k, v in _EDGES.items()}


class GlobalOutcome(Enum):
    PLANNING_DENIED = "PLANNING_DENIED"
    DENIED = "DENIED"
    COMMITTED_SIMULATED = "COMMITTED_SIMULATED"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class BlastRadius(Enum):
    RESOURCE = "RESOURCE"
    SERVICE = "SERVICE"
    MULTI_SERVICE = "MULTI_SERVICE"
    HOST = "HOST"  # forbidden shadow value
    NETWORK = "NETWORK"  # forbidden shadow value
    UNKNOWN = "UNKNOWN"  # fail closed

    @classmethod
    def from_str(cls, value: str | None) -> "BlastRadius":
        if value is None:
            return cls.UNKNOWN
        try:
            return cls[value.upper()]
        except (KeyError, AttributeError):
            return cls.UNKNOWN


@dataclass(frozen=True, slots=True)
class ServiceSubPlan:
    """Per-service immutable sub-plan.  The parent plan never replaces a child."""

    service_id: str
    service_profile_version: int
    operation: str
    identity_fingerprint: str
    config_fingerprint: str
    dependency_digest: str
    pre_health: str
    required_post_health: str
    rollback_strategy: str
    risk: str
    blast_radius: str
    consumer_set: tuple[str, ...] = ()
    approval_reference: str = ""
    budget_reference: str = ""
    idempotency_key: str = ""

    def fingerprint(self) -> str:
        payload = "|".join(
            [
                self.service_id,
                str(self.service_profile_version),
                self.operation,
                self.identity_fingerprint,
                self.config_fingerprint,
                self.dependency_digest,
                self.pre_health,
                self.required_post_health,
                self.rollback_strategy,
                self.risk,
                self.blast_radius,
                ",".join(self.consumer_set),
                self.approval_reference,
                self.budget_reference,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MultiServiceChangePlan:
    """Immutable multi-service change plan.  Created once, never edited."""

    plan_id: str
    transaction_id: str
    baseline_sha: str
    coordinator_version: str
    created_at: float
    expires_at: float
    service_set: tuple[ServiceSubPlan, ...]
    dependency_graph_digest: str
    execution_order: tuple[str, ...]
    rollback_order: tuple[str, ...]
    operation_set: tuple[str, ...] = ()
    risk_before: str = "LOW"
    risk_after: str = "LOW"
    blast_radius: str = "SERVICE"
    approval_binding: str = ""
    budget_binding: str = ""
    registry_digest: str = ""
    health_contract_digest: str = ""
    plan_hash: str = ""

    def compute_hash(self) -> str:
        body = (
            self.plan_id,
            self.transaction_id,
            self.baseline_sha,
            self.coordinator_version,
            str(self.created_at),
            str(self.expires_at),
            ",".join(sp.fingerprint() for sp in self.service_set),
            self.dependency_graph_digest,
            ",".join(self.execution_order),
            ",".join(self.rollback_order),
            ",".join(self.operation_set),
            self.risk_before,
            self.risk_after,
            self.blast_radius,
            self.approval_binding,
            self.budget_binding,
            self.registry_digest,
            self.health_contract_digest,
        )
        return hashlib.sha256("\u001f".join(body).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ServiceTransaction:
    """Child transaction bound to one global transaction + generation."""

    global_tx_id: str
    service_id: str
    generation: int
    state: str = "CREATED"
    simulated_success: bool | None = None
    outcome: str | None = None

    @property
    def transaction_id(self) -> str:
        return f"{self.global_tx_id}+{self.service_id}+{self.generation}"


@dataclass(slots=True)
class GlobalTransaction:
    """Global transaction container.  Exactly one per semantic intent."""

    plan: MultiServiceChangePlan
    transaction_id: str
    state: CoordinatorState = CoordinatorState.CREATED
    children: list[ServiceTransaction] = field(default_factory=list)
    denial_reason: str | None = None
    outcome: GlobalOutcome | None = None

    def child(self, service_id: str) -> ServiceTransaction | None:
        for c in self.children:
            if c.service_id == service_id:
                return c
        return None


@dataclass(frozen=True, slots=True)
class PreparedServiceToken:
    """Immutable single-use prepare token bound to the full global context."""

    token_id: str
    global_tx_id: str
    service_transaction_id: str
    plan_hash: str
    service_id: str
    profile_version: int
    registry_digest: str
    identity_fingerprint: str
    config_fingerprint: str
    dependency_digest: str
    approval_reference: str
    budget_reference: str
    lock_nonce: str
    pre_health: str
    required_post_health: str
    risk: str
    blast_radius: str
    expires_at: float
    generation: int = 1

    def binding_digest(self) -> str:
        body = (
            self.global_tx_id,
            self.service_transaction_id,
            self.plan_hash,
            self.service_id,
            str(self.profile_version),
            self.registry_digest,
            self.identity_fingerprint,
            self.config_fingerprint,
            self.dependency_digest,
            self.approval_reference,
            self.budget_reference,
            self.lock_nonce,
            self.pre_health,
            self.required_post_health,
            self.risk,
            self.blast_radius,
        )
        return hashlib.sha256("\u001f".join(body).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PrepareBarrier:
    """Barrier every child must reach READY on before the parent advances."""

    global_tx_id: str
    required_services: tuple[str, ...]
    service_states: dict[str, str] = field(default_factory=dict)
    ready_services: set[str] = field(default_factory=set)

    def mark(self, service_id: str, state: str) -> None:
        if state == "READY":
            self.ready_services.add(service_id)
        else:
            self.ready_services.discard(service_id)
        self.service_states[service_id] = state

    @property
    def all_ready(self) -> bool:
        return set(self.required_services) == self.ready_services


@dataclass(frozen=True, slots=True)
class CompensationStep:
    service_id: str
    operation: str
    order: int
    reverse_order: int
    action: object = None
    preconditions: tuple[str, ...] = ()
    evidence: str = ""
    unsupported: bool = False


@dataclass(frozen=True, slots=True)
class CompensationPlan:
    global_tx_id: str
    steps: tuple[CompensationStep, ...]
    rollback_supported: bool = True

    def ordered_steps(self, reverse: bool = False) -> list[CompensationStep]:
        key = "reverse_order" if reverse else "order"
        return sorted(self.steps, key=lambda s: getattr(s, key))


@dataclass(frozen=True, slots=True)
class MultiServiceExecutionPermit:
    """Simulation-only permit.  Never grants real execution authority.

    execution_guard ALWAYS returns MULTI_SERVICE_EXECUTION_DISABLED even when
    this permit exists and is internally valid.
    """

    permit_id: str
    global_tx_id: str
    plan_hash: str
    registry_digest: str
    execution_order: tuple[str, ...]
    rollback_order: tuple[str, ...]
    issued_at: float
    expires_at: float
    simulation_only: bool = True


def _can_transition(old: CoordinatorState, new: CoordinatorState) -> bool:
    edges = _EDGES.get(old, frozenset())
    if new in edges:
        return True
    # Allow any non-terminal -> failure corridor explicitly.
    if (
        old not in TERMINAL_STATES
        and new
        in {
            CoordinatorState.COMPENSATION_REQUIRED,
            CoordinatorState.UNKNOWN_OUTCOME,
            CoordinatorState.MANUAL_REVIEW_REQUIRED,
            CoordinatorState.COMPENSATION_FAILED,
        }
    ):
        return True
    return False


def check_transition(old: CoordinatorState, new: CoordinatorState) -> bool:
    return _can_transition(old, new)


def json_record(obj) -> str:
    """Canonical JSON for hashing / durable storage (sorted, compact)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


__all__ = [
    "BlastRadius",
    "CompensationPlan",
    "CompensationStep",
    "CoordinatorState",
    "FAILURE_STATES",
    "GlobalOutcome",
    "GlobalTransaction",
    "MultiServiceChangePlan",
    "MultiServiceExecutionPermit",
    "PrepareBarrier",
    "PreparedServiceToken",
    "ServiceSubPlan",
    "ServiceTransaction",
    "TERMINAL_STATES",
    "check_transition",
    "json_record",
]