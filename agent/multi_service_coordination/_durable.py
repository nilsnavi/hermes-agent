"""Sprint 1.3.15 — durable coordination store + append-only event journal.

Isolated Hermes-owned store (NOT production state.db).  All durable state is
written through the shared atomic JSON transaction helper (temp + fsync +
rename + fsync parent).  Events are append-only and monotonically ordered.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from agent.service_restart_policy._durable import JsonTransaction, require_finite_time


class EventJournal:
    """Append-only journal.  Once written an event is never mutated."""

    def __init__(self, root) -> None:
        self._tx = JsonTransaction(root, "event-journal")

    def append(self, event_type: str, payload: dict | None = None) -> int:
        """Appends an event; returns its sequence number (1-based)."""
        now = time.time()

        def change(data):
            seq = int(data.get("next_seq", 0)) + 1
            data["next_seq"] = seq
            events = data.setdefault("events", [])
            events.append(
                {
                    "seq": seq,
                    "type": event_type,
                    "wall": now,
                    "payload": payload or {},
                }
            )
            return seq

        return self._tx.update(change)

    def replay(self) -> list[dict]:
        data = self._tx.read()
        events = data.get("events", [])
        return sorted(events, key=lambda e: e["seq"])

    def types(self) -> list[str]:
        return [e["type"] for e in self.replay()]

    def count(self, event_type: str) -> int:
        return sum(1 for e in self.replay() if e["type"] == event_type)


def _bounded_json(root, name: str) -> JsonTransaction:
    return JsonTransaction(root, name)


class CoordinationStore:
    """File-backed isolated coordination state with atomic critical transitions."""

    def __init__(self, root: str | Path, *, journal: EventJournal | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal = journal or EventJournal(self.root / "events")
        self._global = _bounded_json(self.root, "global-transaction")
        self._children = _bounded_json(self.root, "child-transactions")
        self._idem = _bounded_json(self.root, "idempotency")
        self._approvals = _bounded_json(self.root, "approval-bindings")
        self._budgets = _bounded_json(self.root, "budget-reservations")
        self._recovery = _bounded_json(self.root, "recovery-state")

    # -- global transaction ------------------------------------------------
    def transition_global(self, txid: str, state: str, **extra) -> bool:
        def change(data):
            rec = data.setdefault(txid, {})
            old = rec.get("state")
            rec.update({"state": state, "updated": time.time(), **extra})
            rec["prior_state"] = old
            return True

        return self._global.update(change)

    def get_global(self, txid: str) -> dict | None:
        return self._global.read().get(txid)

    def list_globals(self) -> dict[str, dict]:
        return dict(self._global.read())

    # -- child transactions --------------------------------------------------
    def upsert_child(
        self, global_tx_id: str, service_id: str, generation: int, state: str, **extra
    ) -> bool:
        def change(data):
            key = f"{global_tx_id}+{service_id}+{generation}"
            data[key] = {
                "global_tx_id": global_tx_id,
                "service_id": service_id,
                "generation": generation,
                "state": state,
                "updated": time.time(),
                **extra,
            }
            return True

        return self._children.update(change)

    def get_child(self, child_tx_id: str) -> dict | None:
        return self._children.read().get(child_tx_id)

    def list_children(self, global_tx_id: str) -> list[dict]:
        return [
            r for r in self._children.read().values()
            if r.get("global_tx_id") == global_tx_id
        ]

    # -- idempotency ----------------------------------------------------------
    def claim_global(self, semantic_key: str, owner_id: str, state: str = "CLAIMED") -> str:
        """Exactly-once global claim.  Returns CLAIMED_BY_ME / ALREADY_MINE /
        CLAIMED_BY_OTHER / ALREADY_TERMINAL / UNKNOWN."""
        def change(data):
            rec = data.get(semantic_key)
            if rec is None:
                data[semantic_key] = {
                    "owner_id": owner_id,
                    "state": state,
                    "claimed_at": time.time(),
                }
                return "CLAIMED_BY_ME"
            # A terminal prior on the SAME semantic key is a duplicate
            # regardless of owner: the intent is already decided, replay it.
            if rec.get("state") in {"COMMITTED_SIMULATED", "DENIED", "COMPENSATION_FAILED"}:
                return "ALREADY_TERMINAL"
            if rec.get("owner_id") == owner_id:
                return "ALREADY_MINE"
            return "CLAIMED_BY_OTHER"

        return self._idem.update(change)

    def get_idem(self, semantic_key: str) -> dict | None:
        return self._idem.read().get(semantic_key)

    def idempotency_all(self) -> dict[str, dict]:
        return dict(self._idem.read())

    def set_idem_state(self, semantic_key: str, owner_id: str, state: str) -> bool:
        def change(data):
            rec = data.get(semantic_key)
            if rec is None or rec.get("owner_id") != owner_id:
                return False
            rec["state"] = state
            rec["updated"] = time.time()
            return True

        return self._idem.update(change)

    def record_result(self, semantic_key: str, owner_id: str, outcome: str, payload: dict | None = None) -> bool:
        """Record the terminal simulated result so a duplicate intent replays it
        without a second approval/budget/simulation."""
        def change(data):
            rec = data.get(semantic_key)
            if rec is None or rec.get("owner_id") != owner_id:
                return False
            rec["state"] = outcome
            rec["result"] = payload or {}
            rec["updated"] = time.time()
            return True

        return self._idem.update(change)

    # -- approvals -------------------------------------------------------------
    def bind_approval(self, approval_id: str, binding: dict) -> bool:
        def change(data):
            if approval_id in data:
                return False  # immutable
            data[approval_id] = {"binding": binding, "consumed": False}
            return True

        return self._approvals.update(change)

    def consume_approval(self, approval_id: str) -> bool:
        def change(data):
            rec = data.get(approval_id)
            if rec is None or rec.get("consumed"):
                return False
            rec["consumed"] = True
            return True

        return self._approvals.update(change)

    def approval_exists_consumed(self, approval_id: str) -> bool:
        rec = self._approvals.read().get(approval_id)
        return bool(rec and rec.get("consumed"))

    # -- budgets ----------------------------------------------------------------
    def reserve_budget(self, reservation_id: str, binding: dict) -> bool:
        def change(data):
            if reservation_id in data:
                return False
            data[reservation_id] = {"binding": binding, "state": "RESERVED"}
            return True

        return self._budgets.update(change)

    def release_budget(self, reservation_id: str) -> bool:
        def change(data):
            if reservation_id not in data:
                return False
            data[reservation_id]["state"] = "RELEASED"
            return True

        return self._budgets.update(change)

    def budget_reservations(self) -> dict[str, dict]:
        return dict(self._budgets.read())

    # -- recovery -------------------------------------------------------------
    def set_recovery(self, txid: str, classification: str, evidence: dict | None = None) -> bool:
        def change(data):
            data[txid] = {
                "classification": classification,
                "evidence": evidence or {},
                "updated": time.time(),
            }
            return True

        return self._recovery.update(change)

    def get_recovery(self, txid: str) -> dict | None:
        return self._recovery.read().get(txid)


__all__ = ["CoordinationStore", "EventJournal"]