"""Sprint 1.3.17 — durable execution receipt store (§14).

Receipts are sanitized (no secrets / runtime state), keyed by execution id and
replayable for a duplicate intent.  In 1.3.17 receipts record SIMULATION ONLY —
there is no production mutation receipt.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

from agent.service_restart_policy._durable import JsonTransaction, require_finite_time

from .exceptions import ReceiptStoreError  # noqa: F401
from .models import ExecutionReceipt
from .models import service_set_hash


class ExecutionReceiptStore:
    """Durable, append-only, sanitized execution-receipt store."""

    def __init__(self, root: str | Path) -> None:
        self._tx = JsonTransaction(root, "execution-receipts")

    def write(self, receipt: ExecutionReceipt) -> str:
        require_finite_time(receipt.started_at_monotonic)
        require_finite_time(receipt.completed_at_monotonic)

        def change(data):
            records = data.setdefault("receipts", {})
            records[receipt.execution_id] = {
                "execution_id": receipt.execution_id,
                "global_tx_id": receipt.global_tx_id,
                "generation": receipt.generation,
                "plan_hash": receipt.plan_hash,
                "service_set_hash": receipt.service_set_hash,
                "started_at_monotonic": receipt.started_at_monotonic,
                "completed_at_monotonic": receipt.completed_at_monotonic,
                "mode": receipt.mode,
                "child_outcomes": sorted(receipt.child_outcomes),
                "verification_summary": receipt.verification_summary,
                "stabilization_summary": receipt.stabilization_summary,
                "compensation_required": bool(receipt.compensation_required),
                "final_disposition": receipt.final_disposition,
                "adapter_call_count": receipt.adapter_call_count,
                "receipt_hash": receipt.receipt_hash(),
            }
            return True

        self._tx.update(change)
        return receipt.execution_id

    def get(self, execution_id: str) -> dict | None:
        rec = self._tx.read().get("receipts", {}).get(execution_id)
        return copy.deepcopy(rec) if rec else None

    def by_global_tx(self, global_tx_id: str) -> list[dict]:
        return [
            copy.deepcopy(r) for r in self._tx.read().get("receipts", {}).values()
            if r.get("global_tx_id") == global_tx_id
        ]

    def verify(self, execution_id: str) -> bool:
        """Recompute and compare the stored receipt hash (integrity)."""
        rec = self.get(execution_id)
        if rec is None:
            return False
        probe = ExecutionReceipt(
            execution_id=rec["execution_id"], global_tx_id=rec["global_tx_id"],
            generation=rec["generation"], plan_hash=rec["plan_hash"],
            service_set_hash=rec["service_set_hash"],
            started_at_monotonic=rec["started_at_monotonic"],
            completed_at_monotonic=rec["completed_at_monotonic"], mode=rec["mode"],
            child_outcomes=tuple(tuple(x) for x in rec["child_outcomes"]),
            verification_summary=rec["verification_summary"],
            stabilization_summary=rec["stabilization_summary"],
            compensation_required=rec["compensation_required"],
            final_disposition=rec["final_disposition"],
            adapter_call_count=rec["adapter_call_count"],
        )
        return probe.receipt_hash() == rec.get("receipt_hash")


__all__ = ["ExecutionReceiptStore"]