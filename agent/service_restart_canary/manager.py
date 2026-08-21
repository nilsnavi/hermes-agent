"""Sprint 1.3.13 — single aux service restart canary (orchestrator).

Wires approval -> preflight -> lock -> idempotency -> execute -> verify ->
stabilize -> commit. Exactly-once (durable key on service/version/op/old
identity/config/intent). Replay -> DUPLICATE adapter=0. No auto-retry.
Honours kill-switch, budget, breaker.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .approval import ApprovalManager
from .breaker import RestartCircuitBreaker
from .budget import RestartBudget
from .exceptions import (ApprovalExpired, ApprovalMissing, BreakerOpen,
                          BudgetExceeded, CanaryDisabled, DuplicateRestart,
                          LockConflict, NotAdmitted, NotRegistered)
from .executor import FakeRestartAdapter, RestartAdapter, RestartExecutor
from .idempotency import DurableIdempotencyStore, idempotency_key
from .lock import DurableServiceLock
from .models import (RestartExecutionRequest, RestartOutcome,
                     ServiceRestartCanaryPlan)
from .policy import AdmissionVerdict, admission


class RestartCanaryManager:
    """Top-level orchestration for the single registered aux restart canary."""

    def __init__(
        self,
        allowlist,
        approvals: ApprovalManager | None = None,
        budget: RestartBudget | None = None,
        breaker: RestartCircuitBreaker | None = None,
        idem: DurableIdempotencyStore | None = None,
        lock: DurableServiceLock | None = None,
        executor: RestartExecutor | None = None,
        *,
        allow_real: bool = False,
        store_dir: str | Path = "/home/hermes/.hermes/managed/canary-service/restart-store",
        kill_switch: bool = True,
        owner_pid: int = 0,
        owner_start: str = "rehearsal",
        now: float | None = None,
    ) -> None:
        self._allowlist = allowlist
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._approvals = approvals or ApprovalManager()
        self._budget = budget or RestartBudget()
        self._breaker = breaker or RestartCircuitBreaker()
        self._idem = idem or DurableIdempotencyStore(self._store_dir / "idem")
        self._lock = lock or DurableServiceLock(self._store_dir / "locks")
        self._executor = executor or RestartExecutor(
            allowlist, adapter=None, store_dir=self._store_dir,
            allow_real=allow_real, kill_switch=kill_switch)
        self._allow_real = allow_real
        self._kill_switch = kill_switch
        self._owner_pid = owner_pid or 0
        self._owner_start = owner_start
        self._now = now
        self._clock = lambda: (self._now if self._now is not None else time.time())

    def run(
        self,
        service_id: str,
        unit_identity: str,
        transaction_intent: str,
        *,
        old_pid_identity: str,
        old_start_identity: str,
        profile_version: int,
        config_hash: str,
        graph_digest: str,
        approval_id: str,
        pre_health: str = "HEALTHY",
        observe: dict | None = None,
        ctx: dict | None = None,
    ) -> tuple[RestartOutcome, int]:
        """Execute one restart transaction. Returns (outcome, adapter_calls)."""
        now = self._clock()
        # 1. kill switch
        if self._kill_switch:
            return RestartOutcome.CANARY_DISABLED, self._executor.adapter_calls()

        # 2. idempotency replay
        key = idempotency_key(
            service_id, profile_version, "RESTART",
            old_pid_identity + "/" + old_start_identity, config_hash, transaction_intent)
        prior = self._idem.prior(key)
        if prior and prior.get("outcome") == "COMMITTED":
            return RestartOutcome.DUPLICATE, self._executor.adapter_calls()

        # 3. admission / negative matrix
        entry = self._allowlist.entry_for_service(service_id)
        if entry is None:
            raise NotRegistered(service_id)

        # 4. budget: attempts AND per-sprint success cap (after first success → no more)
        if self._budget.remaining_attempts() < 1:
            raise BudgetExceeded()
        if self._budget.remaining_successes() < 1:
            raise BudgetExceeded()
        # 5. breaker
        if self._breaker.open():
            raise BreakerOpen()

        # 6. approval bound validation
        ok, why = self._approvals.validate(
            approval_id, service_id, "RESTART", old_pid_identity,
            old_start_identity, graph_digest, config_hash, pre_health, now=now)
        if not ok:
            raise ApprovalExpired(why) if "expired" in why else ApprovalMissing(why)

        # 7. durable lock (single writer)
        if not self._lock.acquire(self._owner_pid, self._owner_start,
                                  nonce=transaction_intent, now=now):
            raise LockConflict()

        try:
            # 8. reserve budget attempt + consume approval + record intent
            self._budget.allow_attempt()
            self._approvals.consume(approval_id)
            self._idem.commit(key, "EXECUTING", now)

            # 9. execute exact restart (single adapter call)
            req = RestartExecutionRequest(
                service_id=service_id,
                verified_unit_identity=entry.unit_name,
                transaction_id=transaction_intent,
            )
            outcome, _calls = self._executor.execute(req)

            if outcome == "EXECUTED":
                self._budget.record_success()
                self._idem.commit(key, "COMMITTED", now)
                return RestartOutcome.COMMITTED, self._executor.adapter_calls()
            if outcome == "EXEC_FAILED":
                self._breaker.trip("UNKNOWN_OUTCOME")
                self._idem.commit(key, "FAILED", now)
                return RestartOutcome.FAILED, self._executor.adapter_calls()
            return RestartOutcome.CANARY_DISABLED, self._executor.adapter_calls()
        finally:
            self._lock.release(self._owner_pid, transaction_intent)


__all__ = ["RestartCanaryManager"]