"""Sprint 1.3.8 — limited-mutation runtime (reuses canary mechanisms)."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid

from .budget import DurableBudget
from .policy import PolicyEngine
from agent.production_canary.atomic_write import atomic_write, content_hash
from agent.production_canary.lock import LockManager
from agent.production_canary.preflight import SnapshotManager, gather

#: re-export canary atomic lock/snapshot usage


class LimitedPolicyRuntime:
    """Executes an approved, policy-allowed mutation atomically with snapshot,
    lock, verify and rollback. Reuses the certified canary write path.
    """

    def __init__(self, *, engine: PolicyEngine, store_dir: str,
                 resolved: dict[str, str],  # target name -> absolute path (mirror or live)
                 idem_path: str, owner: str = "hermes", health_ok=lambda: True) -> None:
        self.engine = engine
        self.resolved = resolved
        self.store = store_dir
        os.makedirs(store_dir, exist_ok=True)
        self.snap = SnapshotManager(os.path.join(store_dir, "snapshots"))
        self.locks = LockManager(os.path.join(store_dir, "locks"))
        self.owner = owner
        self.health_ok = health_ok
        self._idem = _Idem(idem_path)
        self.adapter_calls = 0
        self.stats = {"success": 0, "rollback": 0, "denied": 0, "budget": 0,
                      "circuit": 0, "duplicate": 0, "unknown": 0, "faults": 0}

    def _target_path(self, name: str) -> str | None:
        return self.resolved.get(name)

    def run(self, *, profile_id: str, target: str, operation: str,
            payload: bytes, approval: dict | None = None, idem: str = "",
            fault_verify: bool = False, budget_max: int = 10,
            resource_mode: str | None = None, verify_fn=None,
            payload_hash_override: str | None = None) -> dict:
        path = self._target_path(target)
        if path is None:
            self.stats["denied"] += 1
            return {"status": "TARGET_UNRESOLVED", "adapter_calls": 0}
        phash = payload_hash_override or content_hash(payload)
        # idempotency (semantic)
        key = idem or hashlib.sha256(
            f"{profile_id}|{target}|{operation}|{phash}".encode()).hexdigest()
        prior = self._idem.get(key)
        if prior is not None:
            self.stats["duplicate"] += 1
            return {"status": "DUPLICATE_ALREADY_COMMITTED", "adapter_calls": 0, "prior": prior}
        # policy decision (raises on deny) -> map to statuses
        try:
            dec = self.engine.evaluate(
                profile_id=profile_id, target=target, operation=operation,
                payload_hash=phash, approval=approval,
                global_success_max=budget_max, resource_mode=resource_mode)
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            self.stats[{"BudgetExceeded": "budget", "CircuitBreakerOpen": "circuit"}.get(name, "denied")] += 1
            return {"status": name, "adapter_calls": 0, "reason": str(exc)}
        if not dec.get("allowed"):
            self.stats["denied"] += 1
            return {"status": "DENIED", "adapter_calls": 0, "reason": dec.get("reason")}
        # approval consumed conceptually; budget attempt recorded
        budget: DurableBudget = self.engine._budget
        budget.record_attempt(profile_id)

        ev = gather(path)
        before = open(path, "rb").read() if os.path.exists(path) else b""
        snap = self.snap.create(f"tx-{uuid.uuid4().hex[:12]}", path, ev, before)
        lock = self.locks.acquire(path, uuid.uuid4().hex, wait_s=2)
        # atomic write via certified path
        try:
            atomic_write(path, payload, mode=0o600)
            self.adapter_calls += 1
        except Exception as exc:
            self.locks.release(lock)
            budget.record_rollback(profile_id)
            self.stats["rollback"] += 1
            return {"status": "WRITE_FAILED", "adapter_calls": self.adapter_calls, "error": str(exc)}

        # independent verification (per-profile injected, else content hash base)
        verr = []
        if fault_verify:
            verr = ["(injected) verification fault"]
        elif verify_fn is not None:
            verr = list(verify_fn(path, payload))
        else:
            if not os.path.exists(path) or open(path, "rb").read() != payload:
                verr = ["content mismatch"]
        if verr:
            # rollback byte-for-byte
            try:
                self._restore(path, before)
                budget.record_rollback(profile_id)
                self.stats["rollback"] += 1
                budget.bump(profile_id, "consecutive_verify")
                self.locks.release(lock)
                return {"status": "VERIFY_FAILED_ROLLED_BACK", "adapter_calls": self.adapter_calls,
                        "errors": verr}
            except Exception as exc:
                self.locks.release(lock)
                budget.bump(profile_id, "rollback_failed")
                return {"status": "ROLLBACK_FAILED", "adapter_calls": self.adapter_calls, "error": str(exc)}
        # health gate
        if not self.health_ok():
            try:
                self._restore(path, before)
                budget.record_rollback(profile_id)
                self.stats["rollback"] += 1
                budget.bump(profile_id, "consecutive_health")
                self.locks.release(lock)
                return {"status": "HEALTH_FAILED_ROLLED_BACK", "adapter_calls": self.adapter_calls}
            except Exception:
                self.locks.release(lock)
                budget.bump(profile_id, "rollback_failed")
                return {"status": "HEALTH_FAILED_ROLLBACK_FAILED", "adapter_calls": self.adapter_calls}
        self.locks.release(lock)
        budget.record_success(profile_id)
        budget.reset_circuit(profile_id)
        self._idem.put(key, {"status": "COMMITTED", "after_hash": content_hash(payload)})
        self.stats["success"] += 1
        return {"status": "COMMITTED", "adapter_calls": self.adapter_calls,
                "after_hash": content_hash(payload)}

    def _restore(self, path: str, bytes_before: bytes):
        atomic_write(path, bytes_before, mode=0o600)


class _Idem:
    def __init__(self, path: str) -> None:
        self.path = path
        self.d: dict = {}
        if path and os.path.exists(path):
            try:
                self.d = json.load(open(path))
            except (OSError, ValueError):
                self.d = {}

    def get(self, k: str) -> dict | None:
        return self.d.get(k)

    def put(self, k: str, v: dict) -> None:
        self.d[k] = v
        if self.path:
            with open(self.path, "w") as f:
                json.dump(self.d, f)
                f.flush()
                os.fsync(f.fileno())
