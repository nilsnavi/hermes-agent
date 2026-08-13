"""Agent Runtime Core (Sprint 1.0.1) — Hermes Agent 2.0 lifecycle foundation.

Owns the agent-run lifecycle model ONLY. Pure, deterministic, stdlib-only
(no gateway / scheduler / provider / router imports).

    User Request
         │
         ▼
    Agent Run        ← models.py (AgentRun)
         │
         ▼
    State Machine    ← state_machine.py (deterministic, fail-closed)
         │
         ▼
    Task Context     ← context.py (TaskContext)
         │
         ▼
    Lifecycle Mgmt   ← run_engine.py (create / start / complete / fail)

Sprint 1.0.1 is STANDALONE: nothing in the production runtime imports this
package; it is exercised by tests/runtime/ only. Runtime integration lands in
a later sprint (Sprint 1.0.2 Execution Engine).
"""

from .context import TaskContext
from .events import RuntimeEvent
from .exceptions import InvalidStateTransition, RuntimeErrorBase
from .models import AgentRun
from .run_engine import RunEngine
from .state_machine import can_transition, transition
from .states import RunStatus

__all__ = [
    "AgentRun",
    "RunStatus",
    "TaskContext",
    "RunEngine",
    "RuntimeEvent",
    "can_transition",
    "transition",
    "RuntimeErrorBase",
    "InvalidStateTransition",
]
