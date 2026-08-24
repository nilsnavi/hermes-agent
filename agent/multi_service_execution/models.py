"""Sprint 1.3.17 — bounded multi-service execution data model.

Immutable ``MultiServiceExecutionPlan`` wraps the certified coordination plan
(``MultiServiceChangePlan``) and adds execution binding, a strict global +
child state machine, the adapter-outcome contract and a sanitized durable
execution receipt.

This module NEVER grants authority.  These are pure data + deterministic
classification structures.

RECOVERY/EXECUTION NOTE: ``SIMULATED_COMMITTED`` is the ONLY global success
and is reachable only by the coordinator-owned commit path after every child
verified, stabilized and no drift exists.  Adapter ``SUCCEEDED`` alone is
NEVER global success.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from agent.multi_service_coordination.models import (
    BlastRadius,
    MultiServiceChangePlan,
    json_record as coord_json_record,
)

# ---------------------------------------------------------------------------
# Execution mode
# ---------------------------------------------------------------------------


class ExecutionMode(Enum):
    OFF = "off"
    SHADOW = "shadow"
    REHEARSAL = "rehearsal"
    CANARY = "canary"

    @classmethod
    def from_str(cls, value: str | None) -> "ExecutionMode":
        if value is None:
            return cls.OFF
        try:
            return cls[value.upper()]
        except (KeyError, AttributeError):
            return cls.OFF

    def permits_simulated_execution(self) -> bool:
        """Simulated (fake-adapter) execution is allowed only in shadow /
        rehearsal.  OFF and CANARY have no simulated path in 1.3.17."""
        return self in (ExecutionMode.SHADOW, ExecutionMode.REHEARSAL)


# ---------------------------------------------------------------------------
# Global execution state machine (§9)
# ---------------------------------------------------------------------------


class GlobalExecutionState(Enum):
    EXECUTION_CREATED = "EXECUTION_CREATED"
    EXECUTION_REVALIDATING = "EXECUTION_REVALIDATING"
    EXECUTION_READY = "EXECUTION_READY"
    EXECUTION_CLAIMED = "EXECUTION_CLAIMED"
    SIMULATED_EXECUTING = "SIMULATED_EXECUTING"
    SIMULATED_VERIFYING = "SIMULATED_VERIFYING"
    SIMULATED_STABILIZING = "SIMULATED_STABILIZING"
    SIMULATED_COMMIT_READY = "SIMULATED_COMMIT_READY"
    SIMULATED_COMMITTED = "SIMULATED_COMMITTED"

    # failure states
    EXECUTION_DENIED = "EXECUTION_DENIED"
    EXECUTION_ABORTED = "EXECUTION_ABORTED"
    EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


TERMINAL_EXECUTION_STATES = frozenset({
    GlobalExecutionState.SIMULATED_COMMITTED,
    GlobalExecutionState.EXECUTION_DENIED,
    GlobalExecutionState.EXECUTION_ABORTED,
    GlobalExecutionState.EXECUTION_UNKNOWN,
    GlobalExecutionState.COMPENSATION_REQUIRED,
    GlobalExecutionState.MANUAL_REVIEW_REQUIRED,
})


# Explicit legal progress transitions (happy path) + fail corridor.
_EXEC_EDGES: dict[GlobalExecutionState, set[GlobalExecutionState]] = {
    GlobalExecutionState.EXECUTION_CREATED: {GlobalExecutionState.EXECUTION_REVALIDATING},
    GlobalExecutionState.EXECUTION_REVALIDATING: {
        GlobalExecutionState.EXECUTION_READY,
        GlobalExecutionState.EXECUTION_DENIED,
    },
    GlobalExecutionState.EXECUTION_READY: {GlobalExecutionState.EXECUTION_CLAIMED},
    GlobalExecutionState.EXECUTION_CLAIMED: {GlobalExecutionState.SIMULATED_EXECUTING},
    GlobalExecutionState.SIMULATED_EXECUTING: {
        GlobalExecutionState.SIMULATED_VERIFYING,
        GlobalExecutionState.EXECUTION_ABORTED,
        GlobalExecutionState.COMPENSATION_REQUIRED,
        GlobalExecutionState.EXECUTION_UNKNOWN,
    },
    GlobalExecutionState.SIMULATED_VERIFYING: {
        GlobalExecutionState.SIMULATED_STABILIZING,
        GlobalExecutionState.EXECUTION_ABORTED,
        GlobalExecutionState.MANUAL_REVIEW_REQUIRED,
    },
    GlobalExecutionState.SIMULATED_STABILIZING: {
        GlobalExecutionState.SIMULATED_COMMIT_READY,
        GlobalExecutionState.MANUAL_REVIEW_REQUIRED,
        GlobalExecutionState.EXECUTION_ABORTED,
    },
    GlobalExecutionState.SIMULATED_COMMIT_READY: {
        GlobalExecutionState.SIMULATED_COMMITTED,
        GlobalExecutionState.EXECUTION_ABORTED,
        GlobalExecutionState.MANUAL_REVIEW_REQUIRED,
    },
}

# Fail corridor: from any non-terminal state, a terminal failure state is a
# valid abort sink.
_FAIL_CORRIDOR = TERMINAL_EXECUTION_STATES - {GlobalExecutionState.SIMULATED_COMMITTED}
for _s, _targets in list(_EXEC_EDGES.items()):
    _EXEC_EDGES[_s] = _targets | _FAIL_CORRIDOR
_EXEC_EDGES = {k: frozenset(v) for k, v in _EXEC_EDGES.items()}


def can_transition(old: GlobalExecutionState, new: GlobalExecutionState) -> bool:
    return new in _EXEC_EDGES.get(old, frozenset())


# ---------------------------------------------------------------------------
# Child execution state machine (§10)
# ---------------------------------------------------------------------------


class ChildExecutionState(Enum):
    CHILD_READY = "CHILD_READY"
    CHILD_CLAIMED = "CHILD_CLAIMED"
    CHILD_SIMULATED_EXECUTING = "CHILD_SIMULATED_EXECUTING"
    CHILD_SIMULATED_SUCCEEDED = "CHILD_SIMULATED_SUCCEEDED"
    CHILD_SIMULATED_FAILED = "CHILD_SIMULATED_FAILED"
    CHILD_SIMULATED_UNKNOWN = "CHILD_SIMULATED_UNKNOWN"
    CHILD_VERIFIED = "CHILD_VERIFIED"
    CHILD_COMPENSATION_REQUIRED = "CHILD_COMPENSATION_REQUIRED"
    CHILD_TERMINAL = "CHILD_TERMINAL"


# ---------------------------------------------------------------------------
# Adapter outcome contract (§11)
# ---------------------------------------------------------------------------


class AdapterOutcome(Enum):
    ADAPTER_SUCCEEDED = "ADAPTER_SUCCEEDED"
    ADAPTER_FAILED = "ADAPTER_FAILED"
    ADAPTER_UNKNOWN_OUTCOME = "ADAPTER_UNKNOWN_OUTCOME"

    @classmethod
    def from_str(cls, value: str | None) -> "AdapterOutcome":
        if value is None:
            return cls.ADAPTER_UNKNOWN_OUTCOME
        try:
            return cls[value.upper()]
        except (KeyError, AttributeError):
            return cls.ADAPTER_UNKNOWN_OUTCOME


# ---------------------------------------------------------------------------
# Per-child execution binding (§4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChildExecutionBinding:
    """Immutable per-service execution binding."""

    service_id: str
    child_tx_id: str
    child_generation: int
    profile_version: int
    identity_fingerprint: str
    config_fingerprint: str
    graph_fingerprint: str
    risk: str
    blast_radius: str
    approval_id: str
    budget_reservation_id: str
    lock_nonce: str
    prepared_token_hash: str
    operation: str
    expected_effect: str
    rollback_strategy: str
    verification_contract: str

    def binding_digest(self) -> str:
        payload = "|".join([
            self.service_id, self.child_tx_id, str(self.child_generation),
            str(self.profile_version), self.identity_fingerprint,
            self.config_fingerprint, self.graph_fingerprint, self.risk,
            self.blast_radius, self.approval_id, self.budget_reservation_id,
            self.lock_nonce, self.prepared_token_hash, self.operation,
            self.expected_effect, self.rollback_strategy,
            self.verification_contract,
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Immutable multi-service execution plan (§4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MultiServiceExecutionPlan:
    """Immutable execution plan bound to a certified coordination plan."""

    global_tx_id: str
    generation: int
    baseline_sha: str
    service_set: tuple[str, ...]
    topological_order: tuple[str, ...]
    global_plan_hash: str
    graph_digest: str
    registry_digest: str
    approval_digest: str
    budget_digest: str
    lockset_digest: str
    recovery_generation: int
    created_at_monotonic: float
    expires_at_monotonic: float
    execution_mode: ExecutionMode
    children: tuple[ChildExecutionBinding, ...] = ()
    source_plan_hash: str = ""
    source_plan: MultiServiceChangePlan | None = None

    def plan_hash(self) -> str:
        body = (
            self.global_tx_id, str(self.generation), self.baseline_sha,
            ",".join(self.service_set), ",".join(self.topological_order),
            self.global_plan_hash, self.graph_digest, self.registry_digest,
            self.approval_digest, self.budget_digest, self.lockset_digest,
            str(self.recovery_generation), str(self.created_at_monotonic),
            str(self.expires_at_monotonic), self.execution_mode.value,
            ",".join(c.binding_digest() for c in self.children),
        )
        return hashlib.sha256("\u001f".join(body).encode("utf-8")).hexdigest()

    def expired(self, now_monotonic: float) -> bool:
        return now_monotonic > self.expires_at_monotonic

    def child(self, service_id: str) -> ChildExecutionBinding | None:
        for c in self.children:
            if c.service_id == service_id:
                return c
        return None

    def has_all_children_ready(self, child_states: Mapping[str, ChildExecutionState]) -> bool:
        return set(self.service_set) <= set(child_states)


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    """Sanitized durable execution receipt (§14).  Simulation only in 1.3.17."""

    execution_id: str
    global_tx_id: str
    generation: int
    plan_hash: str
    service_set_hash: str
    started_at_monotonic: float
    completed_at_monotonic: float
    mode: str
    child_outcomes: tuple[tuple[str, str], ...]  # (service_id, outcome) sorted
    verification_summary: str
    stabilization_summary: str
    compensation_required: bool
    final_disposition: str
    adapter_call_count: int

    def receipt_hash(self) -> str:
        child = json.dumps(sorted(self.child_outcomes), separators=(",", ":"))
        body = "|".join([
            self.execution_id, self.global_tx_id, str(self.generation),
            self.plan_hash, self.service_set_hash,
            str(self.started_at_monotonic), str(self.completed_at_monotonic),
            self.mode, child, self.verification_summary,
            self.stabilization_summary, str(self.compensation_required),
            self.final_disposition, str(self.adapter_call_count),
        ])
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


def semantic_execution_key(plan: MultiServiceExecutionPlan) -> str:
    """Exactly-once durable claim key (§13): global_tx + generation + baseline
    + plan_hash + service_set + operation_set.  Time-invariant."""
    raw = "|".join([
        plan.global_tx_id, str(plan.generation), plan.baseline_sha,
        plan.global_plan_hash, ",".join(plan.service_set),
        ",".join(c.operation for c in plan.children),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def service_set_hash(service_set: tuple[str, ...]) -> str:
    return hashlib.sha256(",".join(service_set).encode("utf-8")).hexdigest()


__all__ = [
    "AdapterOutcome",
    "BlastRadius",
    "ChildExecutionBinding",
    "ChildExecutionState",
    "ExecutionMode",
    "ExecutionReceipt",
    "GlobalExecutionState",
    "MultiServiceExecutionPlan",
    "TERMINAL_EXECUTION_STATES",
    "can_transition",
    "semantic_execution_key",
    "service_set_hash",
]