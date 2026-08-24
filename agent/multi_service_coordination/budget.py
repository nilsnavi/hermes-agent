"""Sprint 1.3.15 — global coordination budget + child reservation semantics.

Two budgets are kept separate:
  * global coordination budget  — how many coordinated simulations may run
  * child mutation budgets      — each child's own mutation budget

In Sprint 1.3.15 production mutation usage == 0.  Simulation never consumes a
production success budget, but prepare reservation semantics ARE exercised.
"""
from __future__ import annotations

import time
from pathlib import Path

from agent.service_restart_policy._durable import JsonTransaction


class CoordinationBudget:
    def __init__(
        self,
        root: str | Path,
        *,
        global_simulation_cap: int = 100,
        clock=lambda: time.time(),
    ) -> None:
        self._tx = JsonTransaction(root, "coordination-budget")
        self.global_simulation_cap = global_simulation_cap
        self.clock = clock

    def snapshot(self) -> dict:
        return self._tx.read()

    def reserve_global_simulation(self) -> bool:
        def change(data):
            used = int(data.get("global_simulations", 0))
            if used >= self.global_simulation_cap:
                # still reserve semantics: reflect the block
                return False
            data["global_simulations"] = used + 1
            data["last_reservation_wall"] = self.clock()
            return True

        return self._tx.update(change)

    def consumed_global_simulations(self) -> int:
        return int(self._tx.read().get("global_simulations", 0))

    def production_mutation_usage(self) -> int:
        return 0  # simulation never touches production mutation budget


class ChildBudgetReservation:
    """Semantic reservation for one child's mutation budget.  In 1.3.15 this
    reserves a *prepared slot*, never a production mutation."""

    def __init__(self, root: str | Path, *, clock=lambda: time.time()) -> None:
        self._tx = JsonTransaction(root, "child-budget-reservations")
        self.clock = clock

    def reserve(self, reservation_id: str, service_id: str, txid: str) -> bool:
        def change(data):
            if reservation_id in data:
                return False  # single-use
            data[reservation_id] = {
                "service_id": service_id,
                "txid": txid,
                "state": "RESERVED",
                "wall": self.clock(),
            }
            return True

        return self._tx.update(change)

    def release(self, reservation_id: str) -> bool:
        def change(data):
            if reservation_id not in data:
                return False
            data[reservation_id]["state"] = "RELEASED"
            return True

        return self._tx.update(change)

    def list(self) -> dict[str, dict]:
        return dict(self._tx.read())


__all__ = ["ChildBudgetReservation", "CoordinationBudget"]