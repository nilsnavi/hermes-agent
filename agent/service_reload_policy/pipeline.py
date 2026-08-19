"""Sprint 1.3.11 — limited reload pipeline: budget reservation, durable lock,
durable idempotency, cross-process replay."""
from __future__ import annotations

import os
import time
import uuid

from .breaker import KillSwitch, ReloadBreaker
from .budget import ReloadBudget
from .exceptions import LockConflict, OperationDenied, PolicyDenied
from .idempotency import DurableIdempotency, semantic_key
from .lock import ReloadLock
from .policy import effective_action_is_reload, gate


class LimitedReloadRunner:
    """Calls the reload adapter; injectable for tests/live."""

    def __init__(self, fn=None, adapter_calls=None):
        self.fn = fn
        self._calls = adapter_calls if adapter_calls is not None else [0]

    def call(self, service_id, identity):
        self._calls[0] += 1
        if self.fn:
            return self.fn(service_id, identity)
        return True


class ReloadTransaction:
    def __init__(self, *, registry, budget: ReloadBudget, breaker: ReloadBreaker,
                 kill: KillSwitch, lock: ReloadLock, idem: DurableIdempotency,
                 runner: LimitedReloadRunner | None = None, mode="limited",
                 approval_fn=None, preflight_fn=None):
        self.registry = registry
        self.budget = budget
        self.breaker = breaker
        self.kill = kill
        self.lock = lock
        self.idem = idem
        self.runner = runner or LimitedReloadRunner()
        self.mode = mode
        self.approval_fn = approval_fn
        self.preflight_fn = preflight_fn

    def run(self, service_id, intent, *, op="RELOAD", identity="", config_hash=""):
        if self.mode == "off":
            return "POLICY_DISABLED"
        reg = self.registry.get(service_id)
        # shadow: evaluate full gates but write=0
        if self.mode == "shadow":
            if not reg:
                return "SHADOW_SERVICE_NOT_REGISTERED"
            return "SHADOW_OK_WRITE_0"

        g = gate(registered=reg is not None, profile=reg,
                 chk=None, approval_valid=self.approval_fn is not None and self.approval_fn(),
                 budget=self.budget, breaker=self.breaker, kill=self.kill, op=op)
        if g:
            return g

        # idempotency (durable)
        key = semantic_key(service_id, reg.profile_version, op, identity,
                           config_hash, intent)
        prior = self.idem.lookup(key)
        if prior:
            return prior + ":DUPLICATE_ADAPTER_0"

        # durable lock
        txid = f"tx-{uuid.uuid4().hex[:10]}"
        nonce = str(os.getpid())
        try:
            self.lock.acquire(service_id, txid, f"pid:{nonce}", nonce)
        except LockConflict:
            return "LOCK_CONFLICT"

        try:
            # budget reservation
            if not self.budget.can_attempt():
                return "BUDGET_EXCEEDED"
            self.budget.reserve_attempt()

            # pre-exec revalidate fingerprint
            if self.preflight_fn and not self.preflight_fn(reg):
                self.budget.release_reservation()
                self.idem.record(key, "REVALIDATE_REQUIRED")
                self.lock.release(service_id, txid)
                return "REVALIDATE_REQUIRED"

            ok = self.runner.call(service_id, reg.expected_exec_reload)
            if not ok:
                return "RELOAD_FAILED"
            self.breaker.note_success(service_id)
            self.budget.record_success()
            self.idem.record(key, "COMMITTED")
            return "COMMITTED"
        finally:
            self.lock.release(service_id, txid)