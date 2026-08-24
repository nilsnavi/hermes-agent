"""Sole authority coordinator for a default-off limited restart transaction."""
from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .approval import ApprovalContract, DurableApprovalStore
from ._durable import JsonTransaction, require_finite_time
from .breaker import DurableCircuitBreaker
from .budget import DurableHourlyBudgets
from .clock import Clock, SystemClock
from .executor import BoundedRestartExecutor
from .idempotency import DurableIdempotencyStore, semantic_key
from .lock import HardenedServiceLock, _linux_process_start
from .models import AdmissionContext, ExecutionResult, RestartExecutionRequest
from .policy import RestartAdmission
from .registry import RestartProfileRegistry


@dataclass(frozen=True, slots=True)
class _RestartExecutionGrant:
    transaction_id: str
    service_id: str
    profile_version: int
    unit: str
    operation: str
    plan_hash: str
    approval_id: str
    identity_fingerprint: str
    graph_digest: str
    config_hash: str
    risk: str
    blast: str
    budget_reservation: str
    lock_nonce: str
    created_monotonic: float
    expires_monotonic: float
    clock_provenance: str
    capability_nonce: str
    instance_token: str
    registry_digest: str


class LimitedRestartRuntime:
    """Runtime is the sole authority coordinator and transaction committer."""

    def __init__(
        self,
        root,
        *,
        runner,
        verifier: Callable[[RestartExecutionRequest], Mapping[str, bool]] | None = None,
        rollout_enabled: bool = False,
        kill_switch: bool = True,
        owner_pid: int | None = None,
        owner_start: str | None = None,
        process_start=_linux_process_start,
        per_service_attempts: int = 2,
        per_service_successes: int = 1,
        global_attempts: int = 4,
        global_successes: int = 2,
        per_service_limit: int | None = None,
        global_limit: int | None = None,
        breaker_threshold: int = 1,
        breaker_cooldown: float = 3600,
        timeout: float = 10.0,
        clock: Clock | None = None,
        grant_ttl: float = 5.0,
        duplicate_wait: float = 2.0,
        pre_adapter_hook: Callable[[object], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.clock = clock or SystemClock()
        provenance_tx = JsonTransaction(self.root / "clock", "provenance")
        def bind_provenance(data):
            prior = data.get("clock_provenance")
            if prior is None:
                data["clock_provenance"] = self.clock.provenance
                data["created_wall"] = require_finite_time(self.clock.wall_time())
                return True
            return prior == self.clock.provenance
        self.clock_provenance_valid = provenance_tx.update(bind_provenance)
        self.registry = RestartProfileRegistry()
        self.registry_digest = self.registry.registry_digest
        self.registry_version = self.registry.registry_version
        # Opaque per-instance provenance token; bound into every issued
        # capability so a capability minted by one runtime instance can never
        # be redeemed by another.
        self.__instance_token = secrets.token_urlsafe(24)
        self.admission = RestartAdmission(self.registry)
        self.approvals = DurableApprovalStore(self.root / "approvals")
        self.budgets = DurableHourlyBudgets(
            self.root / "budgets",
            per_service_limit,
            global_limit,
            per_service_attempts=per_service_attempts,
            per_service_successes=per_service_successes,
            global_attempts=global_attempts,
            global_successes=global_successes,
        )
        self.breaker = DurableCircuitBreaker(
            self.root / "breaker", breaker_threshold, breaker_cooldown
        )
        self.idempotency = DurableIdempotencyStore(
            self.root / "idempotency", clock_provenance=self.clock.provenance
        )
        self.__commit_ready: set[tuple[int, str, str]] = set()
        def transaction_active(service_id: str, transaction_id: str) -> bool:
            return any(
                record.get("owner_id") == transaction_id
                and record.get("state") in {"CLAIMED", "EXECUTING"}
                for record in self.idempotency._tx.read().values()
            )
        self.lock = HardenedServiceLock(
            self.root / "locks",
            process_start=process_start,
            transaction_active=transaction_active,
        )
        self.__issued_grants: dict[int, tuple[_RestartExecutionGrant, dict]] = {}
        self.executor = BoundedRestartExecutor(
            self.registry,
            runner=runner,
            rollout_enabled=rollout_enabled,
            kill_switch=kill_switch,
            timeout=timeout,
            _runtime_owner=self,
        )
        self.verifier = verifier
        self.rollout_enabled = rollout_enabled
        self.kill_switch = kill_switch
        self.owner_pid = os.getpid() if owner_pid is None else owner_pid
        self.owner_start = process_start(self.owner_pid) if owner_start is None else owner_start
        self.grant_ttl = grant_ttl
        self.duplicate_wait = duplicate_wait
        self.pre_adapter_hook = pre_adapter_hook

    @staticmethod
    def _clock_value(clock: Clock) -> float:
        return require_finite_time(clock.monotonic())

    def _monotonic(self) -> float:
        return self._clock_value(self.clock)

    def _consume_commit_ready(
        self, store: DurableIdempotencyStore, key: str, owner_id: str
    ) -> bool:
        capability = (id(store), key, owner_id)
        if store is not self.idempotency or capability not in self.__commit_ready:
            return False
        self.__commit_ready.remove(capability)
        return True

    def _transaction_authority_valid(
        self,
        request: RestartExecutionRequest,
        context: AdmissionContext,
        approval: ApprovalContract,
        *,
        key: str,
        reservation_id: str,
        lock_nonce: str,
    ) -> bool:
        current = self._monotonic()
        idem = self.idempotency.get(key)
        return bool(
            isinstance(idem, dict)
            and idem.get("owner_id") == request.transaction_id
            and idem.get("state") == "EXECUTING"
            and self.approvals.owns_consumed_contract(approval)
            and self.budgets.owns_reservation(
                request.service_id, reservation_id, current
            )
            and self.lock.owns(
                request.service_id, request.transaction_id,
                self.owner_pid, self.owner_start or "", lock_nonce, current,
            )
            and self._bindings_match(request, context, approval)
            and self.admission.decide(context).allowed
        )

    def _issue_execution_grant(
        self,
        request: RestartExecutionRequest,
        context: AdmissionContext,
        approval: ApprovalContract,
        *,
        key: str,
        reservation_id: str,
        lock_nonce: str,
        unit: str,
    ) -> _RestartExecutionGrant:
        now = self._monotonic()
        grant = _RestartExecutionGrant(
            transaction_id=request.transaction_id,
            service_id=request.service_id,
            profile_version=request.profile_version,
            unit=unit,
            operation="RESTART",
            plan_hash=context.plan_hash,
            approval_id=approval.approval_id,
            identity_fingerprint=context.old_process_identity,
            graph_digest=context.graph_digest,
            config_hash=context.config_digest,
            risk=context.risk,
            blast=context.blast_radius.value,
            budget_reservation=reservation_id,
            lock_nonce=lock_nonce,
            created_monotonic=now,
            expires_monotonic=now + self.grant_ttl,
            clock_provenance=self.clock.provenance,
            capability_nonce=secrets.token_urlsafe(32),
            instance_token=self.__instance_token,
            registry_digest=self.registry_digest,
        )
        self.__issued_grants[id(grant)] = (
            grant,
            {
                "request": request, "context": context, "approval": approval,
                "key": key, "reservation_id": reservation_id,
                "lock_nonce": lock_nonce,
            },
        )
        return grant

    def _consume_execution_grant(
        self,
        grant: object,
        request: RestartExecutionRequest,
        unit: str,
        executor: object,
    ) -> str:
        issued = self.__issued_grants.pop(id(grant), None)
        if issued is None or issued[0] is not grant or executor is not self.executor:
            return "EXECUTION_AUTHORITY_MISSING"
        exact, evidence = issued
        now = self._monotonic()
        if (
            exact.clock_provenance != self.clock.provenance
            or now < exact.created_monotonic
            or now > exact.expires_monotonic
        ):
            return "EXECUTION_GRANT_EXPIRED"
        if (
            exact.transaction_id != request.transaction_id
            or exact.service_id != request.service_id
            or exact.profile_version != request.profile_version
            or exact.unit != unit
            or exact.operation != "RESTART"
        ):
            return "EXECUTION_GRANT_BINDING_MISMATCH"
        context = evidence["context"]
        approval = evidence["approval"]
        valid = bool(
            evidence["request"] is request
            and exact.plan_hash == context.plan_hash
            and exact.approval_id == approval.approval_id
            and exact.identity_fingerprint == context.old_process_identity
            and exact.graph_digest == context.graph_digest
            and exact.config_hash == context.config_digest
            and exact.risk == context.risk
            and exact.blast == context.blast_radius.value
            and exact.budget_reservation == evidence["reservation_id"]
            and exact.lock_nonce == evidence["lock_nonce"]
            and exact.instance_token == self.__instance_token
            and exact.registry_digest == self.registry_digest
            and self._transaction_authority_valid(
                request, context, approval,
                key=evidence["key"],
                reservation_id=evidence["reservation_id"],
                lock_nonce=evidence["lock_nonce"],
            )
        )
        return "AUTHORIZED" if valid else "EXECUTION_GRANT_INVALIDATED"

    @staticmethod
    def _bindings_match(
        request: RestartExecutionRequest,
        context: AdmissionContext,
        approval: ApprovalContract,
    ) -> bool:
        if (context.service_id, context.profile_version) != (
            request.service_id, request.profile_version,
        ):
            return False
        if (approval.service_id, approval.profile_version, approval.transaction_id) != (
            request.service_id, request.profile_version, request.transaction_id,
        ):
            return False
        context_binding = (
            context.old_process_identity, context.graph_digest, context.consumer.value,
            context.config_digest, context.health_digest, context.risk,
            context.blast_radius.value, context.quiescence_contract,
            context.startup_contract, context.recovery_contract,
            context.budget_snapshot, context.breaker_snapshot,
            context.plan_hash, context.baseline_sha, context.registry_digest,
        )
        approval_binding = (
            approval.old_process_identity, approval.graph_digest, approval.consumer_state,
            approval.config_digest, approval.health_digest, approval.risk,
            approval.blast, approval.quiescence_contract, approval.startup_contract,
            approval.recovery_contract, approval.budget_snapshot,
            approval.breaker_snapshot, approval.plan_hash, approval.baseline_sha,
            approval.registry_digest,
        )
        return context_binding == approval_binding

    @staticmethod
    def _replay(rec: Mapping | None) -> ExecutionResult:
        if rec and rec.get("state", rec.get("outcome")) == "COMMITTED":
            return ExecutionResult("COMMITTED", adapter_calls=0, replayed=True)
        if rec and rec.get("state") == "FAILED_SAFE":
            return ExecutionResult(str(rec.get("outcome", "FAILED_SAFE")), adapter_calls=0, replayed=True)
        return ExecutionResult("UNKNOWN_OUTCOME", adapter_calls=0)

    def _fail_claim(self, key: str, txid: str, outcome: str) -> None:
        now = self._monotonic()
        state = "UNKNOWN_OUTCOME" if "UNKNOWN_OUTCOME" in outcome else "FAILED_SAFE"
        self.idempotency.transition(
            key, txid, {"CLAIMED", "EXECUTING"}, state, now,
            outcome=outcome, audit_wall=self.clock.wall_time(),
        )

    def execute(
        self,
        request: RestartExecutionRequest,
        context: AdmissionContext,
        approval: ApprovalContract,
    ) -> ExecutionResult:
        try:
            self._monotonic()
        except ValueError:
            return ExecutionResult("INVALID_TIME")
        if not self.clock_provenance_valid:
            return ExecutionResult("CLOCK_PROVENANCE_MISMATCH")
        if self.kill_switch:
            return ExecutionResult("KILL_SWITCH_ACTIVE")
        if not self.rollout_enabled:
            return ExecutionResult("ROLLOUT_DISABLED")
        decision = self.admission.decide(context)
        if not decision.allowed:
            if decision.reason in {
                "IDENTITY_UNVERIFIED", "QUIESCENCE_UNPROVEN", "STARTUP_UNPROVEN",
                "PRE_HEALTH_FAILED", "RECOVERY_UNPROVEN",
            }:
                self.breaker.record_failure(request.service_id, self._monotonic())
            return ExecutionResult(decision.reason)
        if not self._bindings_match(request, context, approval):
            return ExecutionResult("APPROVAL_BINDING_MISMATCH")
        # A3: the runtime's authority comes from its immutable construction-time
        # registry snapshot.  If the plan/approval was bound to a different
        # registry digest (registry changed between plan and execution, or a
        # forged registry was used to build this runtime), deny.
        if self.registry_digest != self.registry.registry_digest:
            return ExecutionResult("REGISTRY_DRIFT")
        bound_digest = getattr(context, "registry_digest", "") or getattr(
            approval, "registry_digest", ""
        )
        if bound_digest and bound_digest != self.registry_digest:
            return ExecutionResult("REGISTRY_DRIFT")
        if self.verifier is None:
            return ExecutionResult("VERIFIER_REQUIRED")

        now = self._monotonic()
        key = semantic_key(request, context)
        claim = self.idempotency.claim(
            key, now, request.transaction_id, audit_wall=self.clock.wall_time()
        )
        if claim == "ALREADY_COMMITTED":
            return self._replay(self.idempotency.get(key))
        if claim == "CLAIMED_BY_OTHER":
            return self._replay(self.idempotency.wait_for_terminal(key, self.duplicate_wait))
        if claim == "UNKNOWN_OUTCOME":
            return ExecutionResult("UNKNOWN_OUTCOME")
        if claim != "CLAIMED_BY_ME":
            return ExecutionResult("MANUAL_REVIEW")

        nonce = secrets.token_urlsafe(24)
        reservation_id = f"{request.transaction_id}:{secrets.token_urlsafe(16)}"
        if not self.lock.acquire(
            request.service_id,
            self.owner_pid,
            self.owner_start or "",
            nonce,
            self._monotonic(),
            transaction_id=request.transaction_id,
        ):
            self._fail_claim(key, request.transaction_id, "LOCK_CONFLICT")
            return ExecutionResult("LOCK_CONFLICT")

        try:
            # Mandatory post-lock duplicate/ownership recheck closes lookup→lock TOCTOU.
            rec = self.idempotency.get(key)
            if rec and rec.get("state", rec.get("outcome")) == "COMMITTED":
                return self._replay(rec)
            if not isinstance(rec, dict) or rec.get("owner_id") != request.transaction_id:
                return self._replay(rec)

            now = self._monotonic()
            approval_verdict = self.approvals.validate_contract(approval, now)
            if approval_verdict != "APPROVED":
                self._fail_claim(key, request.transaction_id, approval_verdict)
                return ExecutionResult(approval_verdict)
            approval_verdict = self.approvals.consume_contract(approval, now)
            if approval_verdict != "APPROVED":
                self._fail_claim(key, request.transaction_id, approval_verdict)
                return ExecutionResult(approval_verdict)
            if not self.budgets.reserve_attempt(
                request.service_id, now, reservation_id=reservation_id
            ):
                self._fail_claim(key, request.transaction_id, "BUDGET_EXCEEDED")
                return ExecutionResult("BUDGET_EXCEEDED")
            if not self.breaker.allow(request.service_id, now):
                self._fail_claim(key, request.transaction_id, "BREAKER_OPEN")
                return ExecutionResult("BREAKER_OPEN")

            # Pre-execution revalidation after all durable reservations.
            if not self.admission.decide(context).allowed:
                self._fail_claim(key, request.transaction_id, "PRE_EXECUTION_REVALIDATION_FAILED")
                return ExecutionResult("PRE_EXECUTION_REVALIDATION_FAILED")
            if not self.idempotency.transition(
                key, request.transaction_id, {"CLAIMED"}, "EXECUTING", now,
                audit_wall=self.clock.wall_time(),
            ):
                return ExecutionResult("MANUAL_REVIEW")
            self.idempotency.set_phase(key, request.transaction_id, "AUTHORIZED", now)

            profile = self.registry.resolve(request.service_id)
            if profile is None:
                self._fail_claim(key, request.transaction_id, "PROFILE_REBIND")
                return ExecutionResult("PROFILE_REBIND")
            grant = self._issue_execution_grant(
                request, context, approval,
                key=key, reservation_id=reservation_id,
                lock_nonce=nonce, unit=profile.unit_name,
            )
            if self.pre_adapter_hook is not None:
                self.pre_adapter_hook(grant)
            self.idempotency.set_phase(
                key, request.transaction_id, "EXECUTING", self._monotonic()
            )
            adapter = self.executor.execute(request, grant)
            if adapter.outcome == "ADAPTER_UNKNOWN_OUTCOME":
                self._fail_claim(key, request.transaction_id, "UNKNOWN_OUTCOME")
                self.breaker.record_failure(request.service_id, self._monotonic())
                return ExecutionResult(
                    "UNKNOWN_OUTCOME", adapter.adapter_calls, adapter.returncode,
                    adapter.stdout, adapter.stderr,
                )
            if adapter.outcome != "ADAPTER_SUCCEEDED":
                self._fail_claim(key, request.transaction_id, adapter.outcome)
                self.breaker.record_failure(request.service_id, self._monotonic())
                return adapter

            self.idempotency.set_phase(
                key, request.transaction_id, "ADAPTER_SUCCEEDED", self._monotonic()
            )
            try:
                verification = dict(self.verifier(request))
            except Exception:
                verification = {}
            self.idempotency.set_phase(
                key, request.transaction_id, "POST_VERIFY", self._monotonic()
            )
            verification_gates = (
                ("expected_transition", "TRANSITION_NOT_OBSERVED", True),
                ("post_identity", "IDENTITY_MISMATCH", True),
                ("config_invariant", "CONFIG_INVARIANT_FAILED", True),
                ("graph_invariant", "GRAPH_INVARIANT_FAILED", True),
                ("health", "HEALTH_FAILED", True),
                ("stabilization", "STABILIZATION_FAILED", True),
                ("forbidden_side_effect", "FORBIDDEN_SIDE_EFFECT", False),
            )
            failed = next(
                (reason for field, reason, expected in verification_gates
                 if verification.get(field) is not expected),
                None,
            )
            if failed is not None:
                self._fail_claim(key, request.transaction_id, failed)
                self.breaker.record_failure(request.service_id, self._monotonic())
                return ExecutionResult(
                    failed, adapter.adapter_calls, adapter.returncode,
                    adapter.stdout, adapter.stderr,
                )

            self.idempotency.set_phase(
                key, request.transaction_id, "STABILIZING", self._monotonic()
            )
            final_now = self._monotonic()
            if not self._transaction_authority_valid(
                request, context, approval,
                key=key, reservation_id=reservation_id, lock_nonce=nonce,
            ):
                self._fail_claim(key, request.transaction_id, "COMMIT_AUTHORITY_LOST")
                return ExecutionResult("COMMIT_AUTHORITY_LOST", adapter.adapter_calls)
            if not self.budgets.record_success(
                request.service_id, final_now, reservation_id=reservation_id
            ):
                self._fail_claim(key, request.transaction_id, "BUDGET_ACCOUNTING_FAILED")
                self.breaker.record_failure(request.service_id, final_now)
                return ExecutionResult("BUDGET_ACCOUNTING_FAILED", adapter.adapter_calls)
            self.__commit_ready.add((id(self.idempotency), key, request.transaction_id))
            if not self.idempotency.coordinator_commit(
                self, key, request.transaction_id, final_now,
                result={"adapter_calls": adapter.adapter_calls, "returncode": adapter.returncode},
                audit_wall=self.clock.wall_time(),
            ):
                return ExecutionResult("UNKNOWN_OUTCOME", adapter.adapter_calls)
            self.breaker.record_success(request.service_id)
            return ExecutionResult(
                "COMMITTED", adapter.adapter_calls, adapter.returncode,
                adapter.stdout, adapter.stderr,
            )
        finally:
            self.lock.release(
                request.service_id,
                self.owner_pid,
                self.owner_start or "",
                nonce,
                transaction_id=request.transaction_id,
            )


__all__ = ["LimitedRestartRuntime"]
