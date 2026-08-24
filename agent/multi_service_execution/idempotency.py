"""Sprint 1.3.17 — durable multi-service execution idempotency (§13).

Exactly-once semantic claim keyed on global_tx + generation + baseline_sha +
plan_hash + service_set + operation_set.  Among N concurrent claimers exactly
one wins; the rest replay the prior disposition (never a second budget /
approval / adapter execution).
"""
from __future__ import annotations

import time
from pathlib import Path

from agent.service_restart_policy._durable import JsonTransaction

CLAIM_STATES = ("UNCLAIMED", "CLAIMED", "EXECUTING", "COMMITTED_SIMULATED",
                "FAILED_SAFE", "UNKNOWN_OUTCOME")
_TERMINAL = {"COMMITTED_SIMULATED", "FAILED_SAFE", "UNKNOWN_OUTCOME"}


class ExecutionIdempotencyStore:
    def __init__(self, root: str | Path) -> None:
        self._tx = JsonTransaction(root, "execution-idempotency")

    def claim(self, semantic_key: str, owner_id: object, state: str = "CLAIMED") -> str:
        if state not in CLAIM_STATES:
            raise ValueError(f"invalid claim state: {state}")

        def change(data):
            rec = data.get(semantic_key)
            if rec is None:
                data[semantic_key] = {
                    "owner_id": owner_id, "state": state,
                    "claimed_at": time.time(),
                }
                return "CLAIMED_BY_ME"
            if rec.get("state") in _TERMINAL:
                return "ALREADY_TERMINAL"
            if rec.get("owner_id") == owner_id:
                return "ALREADY_MINE"
            return "CLAIMED_BY_OTHER"

        return self._tx.update(change)

    def set_state(self, semantic_key: str, owner_id: object, state: str,
                  result: dict | None = None) -> bool:
        if state not in CLAIM_STATES:
            raise ValueError(f"invalid claim state: {state}")

        def change(data):
            rec = data.get(semantic_key)
            if rec is None or rec.get("owner_id") != owner_id:
                return False
            rec["state"] = state
            rec["updated"] = time.time()
            if result is not None:
                rec["result"] = result
            return True

        return self._tx.update(change)

    def get(self, semantic_key: str) -> dict | None:
        return self._tx.read().get(semantic_key)

    def all(self) -> dict[str, dict]:
        return dict(self._tx.read())


__all__ = ["ExecutionIdempotencyStore"]