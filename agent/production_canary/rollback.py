"""Sprint 1.3.7 §21/§22 — rollback (byte-for-byte) + unknown-outcome (retry=0)."""
from __future__ import annotations

import hashlib
import os

from .atomic_write import AtomicWriteError, atomic_write


class RollbackFalseSuccess(Exception):
    pass


def restore_from_snapshot(target: str, snapshot: dict, *, mode: int = 0o600) -> dict:
    """Byte-for-byte restore of the pre-mutation content + verify."""
    before_b64 = snapshot.get("before_bytes_b64")
    if before_b64 is None:
        raise AtomicWriteError("snapshot has no before content to restore")
    import base64
    before = base64.b64decode(before_b64)
    atomic_write(target, before, mode=mode)
    # mandatory rollback verification (false success forbidden)
    result = {
        "restored_sha": hashlib.sha256(open(target, "rb").read()).hexdigest(),
        "expected_sha": snapshot.get("before_hash"),
    }
    if result["restored_sha"] != result["expected_sha"]:
        raise RollbackFalseSuccess(
            f"restore hash {result['restored_sha']} != expected {result['expected_sha']}")
    return result


def classify_outcome(*, execution_started: bool, execution_completed: bool) -> str:
    """UNKNOWN_OUTCOME only when started without proof of completion."""
    if execution_started and not execution_completed:
        return "UNKNOWN_OUTCOME"
    if execution_started and execution_completed:
        return "COMPLETED"
    return "NOT_STARTED"


def unknown_outcome_policy(outcome: str) -> dict:
    """UNKNOWN_OUTCOME -> retry=0; only reconcile / verify / safe rollback / manual review."""
    if outcome == "UNKNOWN_OUTCOME":
        return {
            "retry": 0, "manual_review": True,
            "allow_reconcile": True, "allow_verify": True,
            "allow_rollback_if_provably_safe": True,
        }
    return {"retry": 0, "manual_review": False, "allow_reconcile": False,
            "allow_verify": True, "allow_rollback_if_provably_safe": False}
