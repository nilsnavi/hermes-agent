"""Idempotency + duplicate-action detection (Sprint 1.0.5 / 1.0.6).

Canonical hash helpers live in ``agent.persistence.redaction`` (shared
with the execution engine, which now writes ``input_hash`` /
``idempotency_key`` / ``output_hash`` into every TOOL_* event). This
module re-exports them and adds the journal-based duplicate guard.

Duplicate detection (§37): an action is identified by
``(run_id, step_id, input_hash)`` — the SAME step with DIFFERENT input is
a different action. Legacy events without an ``input_hash`` payload still
match by ``(run_id, step_id)`` so pre-1.0.6 journals remain readable.
"""

import hashlib
from enum import Enum
from typing import Dict, Optional

from agent.execution.events import TOOL_COMPLETED, TOOL_FAILED, TOOL_STARTED
from agent.persistence.redaction import (
    compute_input_hash as _compute_input_hash,
    idempotency_key as _idempotency_key,
)


class DuplicateStatus(Enum):
    NONE = "none"
    STARTED_NO_COMPLETION = "started_no_completion"
    COMPLETED = "completed"


def compute_input_hash(arguments: Optional[Dict]) -> str:
    """Canonical SHA-256 of SCRUBBED arguments (canonical implementation)."""
    return _compute_input_hash(arguments)


def idempotency_key(run_id: str, step_id: str, input_hash: str) -> str:
    """Deterministic per-step-attempt key (canonical implementation)."""
    return _idempotency_key(run_id, step_id, input_hash)


class DuplicateActionDetector:
    """Journal-based duplicate-action guard for one run."""

    def __init__(self, store) -> None:
        self._store = store

    def check(
        self,
        run_id: str,
        step_id: str,
        input_hash: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> DuplicateStatus:
        """Journal state for one (run, step[, input]).

        - COMPLETED when a matching TOOL_COMPLETED exists;
        - STARTED_NO_COMPLETION only when a matching TOOL_STARTED is still
          open — a TOOL_FAILED closes the attempt (retry policy decides);
        - NONE otherwise.

        Matching: always by step_id; when the event carries an input_hash
        and a hash was requested, the hashes must be equal (same step +
        different input = different action). Events without input_hash
        (pre-1.0.6 journals) match by step_id only.
        """
        started = False
        for event in self._store.list_events(run_id=run_id):
            if event.payload.get("step") != step_id:
                continue
            event_hash = event.payload.get("input_hash")
            if (
                input_hash is not None
                and event_hash not in (None, input_hash)
            ):
                continue  # same step, different input → different action
            if (
                idempotency_key is not None
                and event.payload.get("idempotency_key") not in (None, idempotency_key)
            ):
                continue
            if event.event_type == TOOL_COMPLETED:
                return DuplicateStatus.COMPLETED
            if event.event_type == TOOL_FAILED:
                started = False  # attempt resolved (failed) — not ambiguous
            elif event.event_type == TOOL_STARTED:
                started = True
        return DuplicateStatus.STARTED_NO_COMPLETION if started else DuplicateStatus.NONE

    def reused_result(self, plan, step_id: str) -> Optional[Dict]:
        """Stored result for a completed step (result reuse, §33)."""
        step = plan.step(step_id)
        if step is not None and step.result is not None:
            return step.result
        return None
