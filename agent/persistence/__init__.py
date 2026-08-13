"""Hermes Agent 2.0 — Persistence Layer (Sprint 1.0.3).

Durable SQLite storage for the Runtime/Execution layer: runs, plans, steps,
approvals, and the append-only event journal, all under the ``agent_v2_``
namespace inside the existing state.db (or any SQLite file). Recovery
CLASSIFICATION only — no automatic resume.

    Runtime Core (agent/runtime) ──┐
                                  ├──► SQLiteExecutionStore (agent/persistence)
    Execution Engine (agent/execution) ─┘          │
                                                   ▼
                                   agent_v2_runs / _plans / _steps /
                                   _approvals / _events (+ _meta)

Production gateway is NOT integrated (feature flag for a later sprint:
``HERMES_RUNTIME_V2_PERSISTENCE``). Standalone package — tests only.
"""

from .exceptions import ConcurrentUpdateError, PersistenceErrorBase
from .recovery import RecoveryDisposition
from .sqlite_store import SQLiteExecutionStore

# Future production activation flag (documented only; not wired anywhere).
PERSISTENCE_FEATURE_FLAG = "HERMES_RUNTIME_V2_PERSISTENCE"

__all__ = [
    "SQLiteExecutionStore",
    "RecoveryDisposition",
    "PersistenceErrorBase",
    "ConcurrentUpdateError",
    "PERSISTENCE_FEATURE_FLAG",
]
