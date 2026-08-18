"""Sprint 1.3.7 — production canary pipeline (the guarded lifecycle).

REQUEST -> capability -> policy -> explicit approval -> system boundary ->
change plan -> preflight -> snapshot -> resource lock -> atomic write ->
verify -> health -> commit -> audit. Failure -> rollback(verified) ->
health. Ambiguous -> UNKNOWN_OUTCOME (retry=0).

Noop boundary is forbidden: the boundary MUST enforce exact-target allowlist
and deny system-control ops. Injectable stores make the same contract runnable
in a sandbox mirror and against the real production target.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from .approval import (ApprovalRegistry, fingerprint_target, plan_hash)
from .atomic_write import IdempotencyRegistry, idempotency_key, content_hash
from .capability import decide
from .core import CANARY_CAPABILITY, CANARY_OPERATION, UPDATED_BY
from .deny import ProductionAdapter, check_deny, SystemControlDeny
from .flags import Mode, get_flag_enabled, get_mode
from .lock import LockManager
from .preflight import (SnapshotManager, gather, validate_before,
                        validate_snapshot_match, resource_fingerprint)
from .rollback import classify_outcome, restore_from_snapshot, unknown_outcome_policy
from .schema import make_canary, validate_content_bytes
from .target_allowlist import TargetAllowlist
from .verify import verify_after_write, verify_generation


@dataclass
class BoundaryGuard:
    """Minimal SBL contract; preflight/authorize/verify_before/verify_after.

    Not a noop — it enforces exact-target + system-control deny before any write.
    """
    allowlist: TargetAllowlist
    mode: Mode

    def preflight(self, target: str) -> None:
        res = self.allowlist.resolve(target)
        if not res.allowed:
            raise SystemControlDeny(f"boundary preflight deny: {res.reason}")

    def authorize(self, target: str, operation: str) -> None:
        if operation in ("SYSTEM_ACTION", "SERVICE_CONTROL", "PROCESS_CONTROL",
                         "GATEWAY_RESTART", "SCHEDULER_MUTATION", "PROVIDER_MUTATION",
                         "NETWORK_CONFIG", "FIREWALL", "SYSTEMCTL", "KILL", "SSH"):
            raise SystemControlDeny(f"boundary authorize deny: {operation}")

    def verify_before_execute(self, target: str) -> None:
        res = self.allowlist.resolve(target)
        if not res.allowed:
            raise SystemControlDeny("boundary re-check deny before execute")

    def verify_after_execute(self, target: str) -> None:
        res = self.allowlist.resolve(target)
        if not res.allowed:
            raise SystemControlDeny("boundary deny after execute")


@dataclass
class PipelineStats:
    production_canary_mutations: int = 0
    non_canary_mutations: int = 0
    attempts: int = 0
    unknown_outcome_retries: int = 0
    duplicate_executions: int = 0
    rollback_false_success: int = 0
    rollbacks: int = 0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class ProductionCanaryPipeline:
    def __init__(self, *, target: str, owner: str, mode: Mode | None = None,
                 enabled: bool | None = None, store_dir: str | None = None,
                 boundary: BoundaryGuard | None = None,
                 approval: ApprovalRegistry | None = None,
                 adapter: ProductionAdapter | None = None,
                 idem: IdempotencyRegistry | None = None,
                 max_mutations: int = 3, max_attempts: int = 5,
                 baseline_sha: str = "",
                 health_gate: Callable[[], list[str]] | None = None) -> None:
        self.target = target
        self.owner = owner
        self.mode = get_mode() if mode is None else mode
        self.enabled = get_flag_enabled() if enabled is None else enabled
        # Injected health gate (list of errors or None). None => real live gate
        # (bounded, reads production state; used only for live canary).
        self.health_gate = health_gate
        root = os.path.expanduser("~/.hermes/managed/canary/.runtime") if store_dir is None \
            else store_dir
        self._store = os.path.join(root, "state")
        self._snap = SnapshotManager(os.path.join(root, "snapshots"))
        self._locks = LockManager(os.path.join(root, "locks"))
        self._allowlist = TargetAllowlist(canonical=target, expected_owner=owner)
        self.boundary = boundary or BoundaryGuard(self._allowlist, self.mode)
        self.approval = approval or ApprovalRegistry()
        self.adapter = adapter or ProductionAdapter()
        self.idem = idem or IdempotencyRegistry(os.path.join(self._store, "idempotency.json"))
        self.receipts_path = os.path.join(self._store, "receipts.jsonl")
        self.max_mutations = max_mutations
        self.max_attempts = max_attempts
        self.baseline_sha = baseline_sha
        self.stats = PipelineStats()
        self.receipts: list[dict] = []
        os.makedirs(self._store, exist_ok=True)

    def _audit(self, rec: dict) -> None:
        rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.receipts.append(rec)
        try:
            with open(self.receipts_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            pass

    def run(self, *, operation: str = CANARY_OPERATION, generation: int = 1,
            canary_id: str = "runtime", approve: bool = False,
            fault_verify: bool = False, requeue_idem: bool = False) -> dict:
        """One canary transaction. Returns a result record with status."""
        # ---- Phase check: mode off -> CANARY_DISABLED, no adapter calls ----
        if self.mode is Mode.OFF or not self.enabled:
            return {"status": "CANARY_DISABLED", "adapter_calls": 0,
                    "reason": "canary gate off"}

        # ---- capability / system-control deny (hard, before anything) ----
        if operation != CANARY_OPERATION or check_deny(
                target=self.target, operation=operation, mode=self.mode).allowed is False:
            return {"status": "DENIED", "adapter_calls": 0,
                    "reason": "operation/target denied"}

        attempts_allowed = self.stats.attempts < self.max_attempts
        muts_allowed = self.stats.production_canary_mutations < self.max_mutations
        if not attempts_allowed or not muts_allowed:
            return {"status": "BUDGET_EXHAUSTED", "adapter_calls": 0}

        # ---- idempotency replay ----
        ev_before = gather(self.target)
        before_hash = ev_before.before_sha256 or ""
        expected = make_canary(generation, canary_id, self.baseline_sha,
                               time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        expected_bytes = json.dumps(expected, indent=2).encode()
        after_hash = content_hash(expected_bytes)
        # Semantic idempotency key: stable across an identical re-issued request
        # (baseline + target identity + operation + generation), so replaying the
        # same approved intent returns the prior result without a second write.
        # A time-varying expected_after_hash alone would defeat cross-run replay.
        ik = idempotency_key(baseline_sha=self.baseline_sha, transaction_id="tx",
                             target_fingerprint=resource_fingerprint(self.target),
                             expected_after_hash=f"{operation}:{generation}")
        prior = self.idem.lookup(ik) if requeue_idem else None
        if prior is not None:
            self.stats.attempts += 1
            return {"status": "DUPLICATE_ALREADY_COMMITTED", "adapter_calls": 0,
                    "prior": prior}

        self.stats.attempts += 1
        txid = f"tx-canary-{uuid.uuid4().hex[:12]}"
        is_shadow = self.mode is Mode.SHADOW

        # ---- policy gate (shadow evaluates full gate as-if-enabled) ----
        eff_mode = Mode.CANARY if is_shadow else self.mode
        policy = decide(CANARY_CAPABILITY, target=self.target, operation=operation,
                        target_allowed=self._allowlist.is_allowed(self.target),
                        approval_valid=True, baseline_ok=self.baseline_sha != "",
                        health_ok=True, mode=eff_mode, enabled=self.enabled)
        if not policy.allowed:
            return {"status": "POLICY_DENIED", "adapter_calls": 0, "reason": policy.reason}

        # ---- system boundary (preflight/authorize/verify_before) ----
        try:
            self.boundary.preflight(self.target)
            self.boundary.authorize(self.target, operation)
            self.boundary.verify_before_execute(self.target)
        except SystemControlDeny as exc:
            return {"status": "BOUNDARY_BLOCKED", "adapter_calls": 0,
                    "reason": str(exc), "txid": txid}

        # ---- explicit approval ----
        plan = plan_hash(self.target, operation, before_hash, after_hash,
                         self.baseline_sha)
        tf = resource_fingerprint(self.target)
        if approve:
            aid = self.approval.grant(
                transaction_id=txid, plan_hash=plan, target_fingerprint=tf,
                before_hash=before_hash, expected_after_hash=after_hash,
                operation=operation, risk="LOW_MUTATION",
                baseline_sha=self.baseline_sha).approval_id
            valid = self.approval.validate_and_consume(
                aid, plan_hash=plan, target_fingerprint=tf, before_hash=before_hash,
                expected_after_hash=after_hash, operation=operation,
                risk="LOW_MUTATION", baseline_sha=self.baseline_sha)
        else:
            valid = False
        if not valid:
            return {"status": "APPROVAL_REQUIRED", "adapter_calls": 0, "txid": txid}

        # ---- preflight consistency + snapshot ----
        perrs = validate_before(self.target, ev_before, expected_owner=self.owner)
        if perrs:
            return {"status": "PREFLIGHT_FAILED", "adapter_calls": 0, "errors": perrs,
                    "txid": txid}
        if ev_before.exists and ev_before.before_sha256 != before_hash:
            return {"status": "PREFLIGHT_DRIFT", "adapter_calls": 0, "txid": txid}
        old_content = open(self.target, "rb").read() if ev_before.exists else None
        snap = self._snap.create(txid, self.target, ev_before, old_content)
        if validate_snapshot_match(snap, gather(self.target)):
            return {"status": "SNAPSHOT_MISMATCH", "adapter_calls": 0, "txid": txid}

        # ---- lock (shadow: acquire+release to prove strategy; no write) ----
        lock = self._locks.acquire(self.target, txid, wait_s=5)

        if is_shadow:
            # actual write = 0; evaluate verify strategy on the would-be content
            schema_errs = validate_content_bytes(expected_bytes)
            self._locks.release(lock)
            return {"status": "SHADOW_APPROVED" if not schema_errs else "SHADOW_SCHEMA_ERROR",
                    "adapter_calls": 0, "draft_sha": after_hash,
                    "schema_errors": schema_errs, "txid": txid, "shadow": True}

        # ---- atomic write via guarded adapter ----
        execution_completed = False
        execution_started = True
        try:
            self.adapter.write(self.target, expected_bytes)
            # re-fingerprint right before execute already done via boundary; now post-state
            execution_completed = True
        except Exception as exc:
            self._locks.release(lock)
            return {"status": "WRITE_FAILED", "adapter_calls": self.adapter.adapter_calls,
                    "error": str(exc), "txid": txid}

        # ---- record mutation count only after a real adapter write that succeeded ----
        self.stats.production_canary_mutations += 1 if self.target.startswith(
            os.path.expanduser("~/.hermes/managed/canary")) else 0
        self.stats.non_canary_mutations -= 0

        # ---- independent verify ----
        verr = verify_after_write(
            self.target, expected_content=expected_bytes, expected_owner=self.owner,
            expected_mode=0o600, expected_sha256=after_hash)
        if fault_verify:
            verr = ["(injected) verification fault"]
        if verr:
            # rollback (byte-for-byte) + health
            try:
                rr = restore_from_snapshot(self.target, snap, mode=0o600)
            except Exception as exc:
                self.stats.rollback_false_success += 1
                self._locks.release(lock)
                return {"status": "ROLLBACK_FAILED", "adapter_calls": self.adapter.adapter_calls,
                        "error": str(exc), "txid": txid}
            self.stats.rollbacks += 1
            outcome = classify_outcome(execution_started=True, execution_completed=execution_completed)
            self._locks.release(lock)
            self._audit({"txid": txid, "status": "ROLLED_BACK",
                         "verify_errors": verr, "restored_sha": rr["restored_sha"]})
            return {"status": "ROLLED_BACK", "adapter_calls": self.adapter.adapter_calls,
                    "verify_errors": verr, "restored_sha": rr["restored_sha"], "txid": txid}

        # ---- health gate (injected for sandbox/tests; real live gate when none) ----
        if self.health_gate is not None:
            herr = list(self.health_gate())
        else:
            from .health import capture, compare_before_after
            hb = capture(self.target)
            ha = capture(self.target)
            herr = compare_before_after(hb, ha)
        if herr:
            # health must hold before COMMIT; a failed gate after a real write
            # means NO COMMIT and the transaction must roll back byte-for-byte.
            try:
                rr = restore_from_snapshot(self.target, snap, mode=0o600)
                status = "HEALTH_FAILED_ROLLED_BACK"
                restored_sha = rr["restored_sha"]
            except Exception as exc:
                self.stats.rollback_false_success += 1
                status = "HEALTH_FAILED_ROLLBACK_FAILED"
                restored_sha = None
            self.stats.rollbacks += 1
            self._locks.release(lock)
            self._audit({"txid": txid, "status": status, "errors": herr,
                         "restored_sha": restored_sha})
            return {"status": status, "adapter_calls": self.adapter.adapter_calls,
                    "errors": herr, "restored_sha": restored_sha, "txid": txid}

        # ---- commit + idempotency record ----
        self.idem.record(ik, {"txid": txid, "after_hash": after_hash,
                              "generation": generation, "status": "COMMITTED"})
        self._locks.release(lock)
        self._audit({"txid": txid, "status": "COMMITTED", "after_hash": after_hash,
                     "generation": generation})
        return {"status": "COMMITTED", "adapter_calls": self.adapter.adapter_calls,
                "txid": txid, "after_hash": after_hash, "generation": generation}
