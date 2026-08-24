"""Sprint 1.3.16 — durable recovery store.  Isolated Hermes-owned path, atomic
JSON via the shared JsonTransaction.  Claim-first recovery leases with hardened
ownership (foreign renew / spoofed / live-owner takeover DENY).  Append-only
recovery event journal.  Compensation idempotency (exactly-once).

This store is RUNTIME_STATE, reproducibility-independent, and never staged.
"""
from __future__ import annotations

import time
from pathlib import Path

from agent.service_restart_policy._durable import JsonTransaction, require_finite_time


# Recovery event types (append-only, never grant authority).
RECOVERY_EVENTS = (
    "RECOVERY_STARTED", "RECOVERY_CLAIMED", "RECOVERY_STATE_CLASSIFIED",
    "VERIFY_RESUME_STARTED", "VERIFY_RESUME_COMPLETED", "COMPENSATION_PLANNED",
    "COMPENSATION_STARTED", "COMPENSATION_CHILD_COMPLETED", "COMPENSATION_FAILED",
    "MANUAL_REVIEW_REQUIRED", "RECOVERY_COMPLETED",
)

_TERMINAL_RECOVERY = {"RECOVERY_COMPLETED"}
_TERMINAL_COMPENSATION = {"COMPENSATION_FAILED"}


class RecoveryJournal:
    def __init__(self, root) -> None:
        self._tx = JsonTransaction(root, "recovery-journal")

    def append(self, evt: str, detail: dict | None = None) -> None:
        def change(data):
            entries = data.setdefault("events", [])
            entries.append({
                "event": evt, "ts": time.time(),
                "detail": detail or {},
            })
        if evt not in RECOVERY_EVENTS:
            raise ValueError(f"unknown recovery event: {evt}")
        self._tx.update(change)

    def types(self) -> list[str]:
        return [e["event"] for e in self._tx.read().get("events", [])]

    def full(self) -> list[dict]:
        return list(self._tx.read().get("events", []))

    def count(self, evt: str) -> int:
        return sum(1 for t in self.types() if t == evt)


class RecoveryClaimStore:
    """Claim-first durable recovery lease.

    Exactly one recovery owner per (transaction_id, recovery_generation).
    Foreign renewal, spoofed owner and live-owner takeover are DENIED.
    """

    def __init__(self, root, host_identity: str) -> None:
        self._tx = JsonTransaction(root, "recovery-claims")
        self._host = host_identity

    def _key(self, tx_id: str, generation: int) -> str:
        return f"{tx_id}::gen:{generation}"

    def claim(self, tx_id: str, generation: int, *, pid: int,
              process_start_identity: str, runtime_identity: str,
              nonce: str, lease_created: float, lease_expiry: float,
              host_identity: str) -> str:
        """Returns CLAIMED / ALREADY_OWNED.  A live owner is NEVER taken over."""
        require_finite_time(lease_created)
        require_finite_time(lease_expiry)
        key = self._key(tx_id, generation)

        def change(data):
            rec = data.get(key)
            if rec is None:
                data[key] = {
                    "pid": pid, "start": process_start_identity,
                    "runtime": runtime_identity, "host": host_identity,
                    "nonce": nonce, "created": lease_created, "expiry": lease_expiry,
                }
                return "CLAIMED"
            # live owner: never take over
            return "ALREADY_OWNED"

        return self._tx.update(change)

    def renew(self, tx_id: str, generation: int, *, pid: int,
              process_start_identity: str, runtime_identity: str,
              host_identity: str, new_expiry: float) -> bool:
        """Foreign / spoofed / live-owner takeover renewal is DENIED."""
        require_finite_time(new_expiry)
        key = self._key(tx_id, generation)

        def change(data):
            rec = data.get(key)
            if rec is None:
                return False
            if rec.get("host") != host_identity:
                return False  # foreign host renew DENY
            if rec.get("pid") != pid or rec.get("start") != process_start_identity:
                return False  # PID reuse / different process DENY
            if rec.get("runtime") != runtime_identity:
                return False  # spoofed runtime DENY
            rec["expiry"] = new_expiry
            return True

        return self._tx.update(change)

    def get(self, tx_id: str, generation: int) -> dict | None:
        return self._tx.read().get(self._key(tx_id, generation))

    def is_live(self, tx_id: str, generation: int, now_monotonic: float) -> bool:
        rec = self.get(tx_id, generation)
        return rec is not None and now_monotonic < rec.get("expiry", 0)


class CompensationStore:
    """Durable compensation idempotency + compensation terminal state."""

    def __init__(self, root) -> None:
        self._tx = JsonTransaction(root, "recovery-compensation")

    def claim_action(self, semantic_key: str, owner: str) -> str:
        def change(data):
            rec = data.get(semantic_key)
            if rec is None:
                data[semantic_key] = {"owner": owner, "done": False}
                return "CLAIMED"
            of = data[semantic_key]
            if of.get("owner") == owner:
                return "ALREADY_OWNED"
            if of.get("done"):
                return "COMPENSATION_DONE"
            return "OWNED_BY_OTHER"

        return self._tx.update(change)

    def mark_done(self, semantic_key: str, owner: str) -> bool:
        def change(data):
            rec = data.get(semantic_key)
            if rec is None or rec.get("owner") != owner or rec.get("done"):
                return False
            rec["done"] = True
            rec["at"] = time.time()
            return True

        return self._tx.update(change)

    def is_done(self, semantic_key: str) -> bool:
        rec = self._tx.read().get(semantic_key)
        return bool(rec and rec.get("done"))


class ManualReviewStore:
    def __init__(self, root) -> None:
        self._tx = JsonTransaction(root, "recovery-manual-reviews")

    def add(self, tx_id: str, payload: dict) -> None:
        require_finite_time(payload.get("generated_at", time.time()))

        def change(data):
            if payload.get("type") not in ("manual-review", "manual-review-payload"):
                raise ValueError("invalid manual review payload type")
            items = data.setdefault("reviews", [])
            if not any(r.get("transaction_id") == tx_id for r in items):
                items.append(payload)
        self._tx.update(change)

    def for_tx(self, tx_id: str) -> list[dict]:
        return [r for r in self._tx.read().get("reviews", []) if r.get("transaction_id") == tx_id]


class RecoveryStore:
    """Aggregate recovery store (RUNTIME_STATE, isolated, never staged)."""

    def __init__(self, root: str | Path, *, host_identity: str) -> None:
        self.root = Path(root)
        self.journal = RecoveryJournal(self.root)
        self.claims = RecoveryClaimStore(self.root, host_identity)
        self.compensation = CompensationStore(self.root)
        self.manual = ManualReviewStore(self.root)
        self.host_identity = host_identity


__all__ = [
    "RecoveryStore", "RecoveryJournal", "RecoveryClaimStore",
    "CompensationStore", "ManualReviewStore", "RECOVERY_EVENTS",
]