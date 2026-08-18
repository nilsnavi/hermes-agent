"""Durable execution receipts (Sprint 1.3.2 §15, §31-§33).

Every started tool produces a durable receipt that survives process
restart:

    execution_id | tool | input_hash | started_at | status
    + on completion: output_hash | completed_at | final_status

Exactly-once (§13/§42): the store enforces at most ONE receipt per
(run_id, step_id, idempotency_key) — a duplicate insert raises
:class:`DuplicateExecution`, and the executor never invokes a tool
twice for the same key.

Storage follows the project's agent_v2 pattern (§31 — prefer the
existing event/store architecture, extensions additive only): the
SQLite backend adds exactly ONE table
``agent_v2_execution_receipts`` (CREATE TABLE IF NOT EXISTS, no
triggers/FTS, no mutation of existing tables) — the same SQLite
database the agent_v2 store uses, so there is no duplicate execution
database.

Restart recovery (§32): receipts left in STARTED after a process
death (TOOL_STARTED emitted, no terminal event) recover as
UNKNOWN_OUTCOME — the executor NEVER auto-reexecutes. Recovery is
explicit: ``ReceiptStore.recover()`` marks orphaned STARTED receipts
UNKNOWN_OUTCOME; the executor calls it on construction and reports the
recovered count.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .errors import DUPLICATE_ACTION, ExecutionErrorBase
from .models import ExecutionStatus, TERMINAL_STATUSES, utcnow


class DuplicateExecution(ExecutionErrorBase):
    """Exactly-once violation: the (run_id, step_id, idempotency_key)
    triple already has a receipt."""

    def __init__(self, message: str) -> None:
        super().__init__(DUPLICATE_ACTION, message)
        self.error_code = DUPLICATE_ACTION


@dataclass(frozen=True)
class ExecutionReceipt:
    """§15 — durable receipt record."""

    execution_id: str
    run_id: str
    step_id: str
    idempotency_key: str
    tool: str
    input_hash: str
    started_at: str          # ISO UTC
    status: str              # ExecutionStatus value
    output_hash: Optional[str] = None
    completed_at: Optional[str] = None
    final_status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "idempotency_key": self.idempotency_key,
            "tool": self.tool,
            "input_hash": self.input_hash,
            "started_at": self.started_at,
            "status": self.status,
            "output_hash": self.output_hash,
            "completed_at": self.completed_at,
            "final_status": self.final_status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionReceipt":
        return cls(
            execution_id=data["execution_id"],
            run_id=data["run_id"],
            step_id=data["step_id"],
            idempotency_key=data["idempotency_key"],
            tool=data["tool"],
            input_hash=data["input_hash"],
            started_at=data["started_at"],
            status=data["status"],
            output_hash=data.get("output_hash"),
            completed_at=data.get("completed_at"),
            final_status=data.get("final_status"),
        )


class ReceiptStore:
    """Durable receipt store contract (§15).

    Implementations MUST be restart-safe: a receipt written before a
    process death is visible after reopening the store.
    """

    def get(
        self,
        run_id: str,
        step_id: str,
        idempotency_key: str,
    ) -> Optional[ExecutionReceipt]:
        raise NotImplementedError

    def insert(self, receipt: ExecutionReceipt) -> None:
        raise NotImplementedError

    def complete(
        self,
        execution_id: str,
        output_hash: str,
        completed_at: str,
        final_status: str,
    ) -> None:
        raise NotImplementedError

    def mark_unknown(self, execution_id: str, at: str) -> None:
        raise NotImplementedError

    def recover(self) -> List[ExecutionReceipt]:
        """Mark STARTED receipts without a terminal event as
        UNKNOWN_OUTCOME and return them (§32)."""
        raise NotImplementedError

    def all(self) -> List[ExecutionReceipt]:
        raise NotImplementedError


class MemoryReceiptStore(ReceiptStore):
    """In-memory backend (tests / single-process)."""

    def __init__(self) -> None:
        self._by_key: Dict[tuple, ExecutionReceipt] = {}
        self._by_id: Dict[str, ExecutionReceipt] = {}

    def get(
        self,
        run_id: str,
        step_id: str,
        idempotency_key: str,
    ) -> Optional[ExecutionReceipt]:
        return self._by_key.get((run_id, step_id, idempotency_key))

    def insert(self, receipt: ExecutionReceipt) -> None:
        key = (receipt.run_id, receipt.step_id, receipt.idempotency_key)
        if key in self._by_key:
            raise DuplicateExecution(
                f"duplicate execution for {key}: already executed")
        self._by_key[key] = receipt
        self._by_id[receipt.execution_id] = receipt

    def complete(
        self,
        execution_id: str,
        output_hash: str,
        completed_at: str,
        final_status: str,
    ) -> None:
        rec = self._by_id.get(execution_id)
        if rec is None:
            return
        updated = ExecutionReceipt(
            execution_id=rec.execution_id,
            run_id=rec.run_id,
            step_id=rec.step_id,
            idempotency_key=rec.idempotency_key,
            tool=rec.tool,
            input_hash=rec.input_hash,
            started_at=rec.started_at,
            status=final_status,
            output_hash=output_hash,
            completed_at=completed_at,
            final_status=final_status,
        )
        self._by_id[execution_id] = updated
        self._by_key[(rec.run_id, rec.step_id, rec.idempotency_key)] = updated

    def mark_unknown(self, execution_id: str, at: str) -> None:
        rec = self._by_id.get(execution_id)
        if rec is None:
            return
        self.complete(execution_id, rec.output_hash or "", at,
                      ExecutionStatus.UNKNOWN_OUTCOME.value)

    def recover(self) -> List[ExecutionReceipt]:
        recovered = []
        for rec in list(self._by_id.values()):
            if rec.status == ExecutionStatus.STARTED.value:
                self.mark_unknown(rec.execution_id, utcnow().isoformat())
                recovered.append(self._by_id[rec.execution_id])
        return recovered

    def all(self) -> List[ExecutionReceipt]:
        return list(self._by_id.values())


class SQLiteReceiptStore(ReceiptStore):
    """SQLite backend — additive agent_v2 table (§31).

    ``db_path`` — path to the SAME SQLite file the agent_v2 store uses
    (default ``~/.hermes/state.db``). Only one table is created:
    ``agent_v2_execution_receipts``. Additive only — no existing table
    is touched, no triggers, no FTS. Exactly-once is enforced by the
    UNIQUE(run_id, step_id, idempotency_key) constraint.
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS agent_v2_execution_receipts (
        execution_id  TEXT PRIMARY KEY,
        run_id        TEXT NOT NULL,
        step_id       TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        tool          TEXT NOT NULL,
        input_hash    TEXT NOT NULL,
        started_at    TEXT NOT NULL,
        status        TEXT NOT NULL,
        output_hash   TEXT,
        completed_at  TEXT,
        final_status  TEXT,
        UNIQUE (run_id, step_id, idempotency_key)
    )
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        import os
        import sqlite3

        self._sqlite3 = sqlite3
        self._path = db_path or os.path.join(
            os.path.expanduser("~/.hermes"), "state.db")
        conn = self._sqlite3.connect(self._path)
        try:
            conn.execute(self._DDL)
            conn.commit()
        finally:
            conn.close()

    def _connect(self):
        return self._sqlite3.connect(self._path)

    def _row_to_receipt(self, row) -> ExecutionReceipt:
        return ExecutionReceipt(
            execution_id=row[0],
            run_id=row[1],
            step_id=row[2],
            idempotency_key=row[3],
            tool=row[4],
            input_hash=row[5],
            started_at=row[6],
            status=row[7],
            output_hash=row[8],
            completed_at=row[9],
            final_status=row[10],
        )

    def get(
        self,
        run_id: str,
        step_id: str,
        idempotency_key: str,
    ) -> Optional[ExecutionReceipt]:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT * FROM agent_v2_execution_receipts "
                "WHERE run_id=? AND step_id=? AND idempotency_key=?",
                (run_id, step_id, idempotency_key))
            row = cur.fetchone()
            return self._row_to_receipt(row) if row else None
        finally:
            conn.close()

    def insert(self, receipt: ExecutionReceipt) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO agent_v2_execution_receipts "
                "(execution_id, run_id, step_id, idempotency_key, tool, "
                " input_hash, started_at, status) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (receipt.execution_id, receipt.run_id, receipt.step_id,
                 receipt.idempotency_key, receipt.tool, receipt.input_hash,
                 receipt.started_at, receipt.status))
            conn.commit()
        except self._sqlite3.IntegrityError as exc:
            raise DuplicateExecution(
                f"duplicate execution for "
                f"({receipt.run_id}, {receipt.step_id}, "
                f"{receipt.idempotency_key}): {exc}") from exc
        finally:
            conn.close()

    def complete(
        self,
        execution_id: str,
        output_hash: str,
        completed_at: str,
        final_status: str,
    ) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE agent_v2_execution_receipts SET status=?, "
                "output_hash=?, completed_at=?, final_status=? "
                "WHERE execution_id=?",
                (final_status, output_hash, completed_at, final_status,
                 execution_id))
            conn.commit()
        finally:
            conn.close()

    def mark_unknown(self, execution_id: str, at: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE agent_v2_execution_receipts SET status=?, "
                "final_status=?, completed_at=? WHERE execution_id=? "
                "AND status=?",
                (ExecutionStatus.UNKNOWN_OUTCOME.value,
                 ExecutionStatus.UNKNOWN_OUTCOME.value, at, execution_id,
                 ExecutionStatus.STARTED.value))
            conn.commit()
        finally:
            conn.close()

    def recover(self) -> List[ExecutionReceipt]:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT * FROM agent_v2_execution_receipts "
                "WHERE status=?", (ExecutionStatus.STARTED.value,))
            rows = [self._row_to_receipt(r) for r in cur.fetchall()]
            at = utcnow().isoformat()
            for rec in rows:
                self.mark_unknown(rec.execution_id, at)
            return [self._row_to_receipt(r) for r in conn.execute(
                "SELECT * FROM agent_v2_execution_receipts "
                "WHERE status=?",
                (ExecutionStatus.UNKNOWN_OUTCOME.value,)).fetchall()]
        finally:
            conn.close()

    def all(self) -> List[ExecutionReceipt]:
        conn = self._connect()
        try:
            cur = conn.execute("SELECT * FROM agent_v2_execution_receipts")
            return [self._row_to_receipt(r) for r in cur.fetchall()]
        finally:
            conn.close()


__all__ = [
    "ExecutionReceipt",
    "ReceiptStore",
    "MemoryReceiptStore",
    "SQLiteReceiptStore",
    "DuplicateExecution",
]
