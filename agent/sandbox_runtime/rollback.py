"""Rollback (Sprint 1.3.5 §22/§43) — restore snapshot + verify + audit."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .exceptions import RollbackFailed
from .snapshot import Snapshot


@dataclass
class RollbackOutcome:
    status: str
    original_failure: str = ""
    manual_review_required: bool = False
    audit: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RollbackFailureDisposition:
    disposition: str
    original_error: str
    rollback_error: str


def rollback_failure_disposition(original_error: str,
                                 rollback_error: str) -> RollbackFailureDisposition:
    """Preserve both errors; a failed rollback always requires a human."""
    return RollbackFailureDisposition("MANUAL_REVIEW_REQUIRED",
                                      original_error, rollback_error)


class RollbackManager:
    """Rollback goes through the same rigor: restore → verify → health.

    Never hides the original failure: audit carries BOTH reasons.
    """

    def __init__(self, sandbox_root) -> None:
        self._root = sandbox_root

    def rollback(self, txid: str, snapshot: Optional[Snapshot],
                 resolved_target: str,
                 original_failure: str) -> RollbackOutcome:
        audit: Dict[str, Any] = {
            "txid": txid,
            "original_failure": original_failure,
            "rollback_started_at": None,
        }
        if snapshot is None:
            raise RollbackFailed(f"no snapshot for {txid} — cannot rollback")
        try:
            self._root_snapshot_manager().restore(snapshot, resolved_target)
        except Exception as exc:
            audit["rollback_status"] = "ROLLBACK_VERIFY_FAILED"
            audit["rollback_error"] = str(exc)
            return RollbackOutcome(
                status="ROLLBACK_VERIFY_FAILED",
                original_failure=original_failure,
                manual_review_required=True,
                audit=audit)
        # verify rollback: target state must match the snapshot manifest
        try:
            ok = self._verify_restored(snapshot, resolved_target)
        except Exception:
            ok = False
        if not ok:
            audit["rollback_status"] = "ROLLBACK_VERIFY_FAILED"
            return RollbackOutcome(
                status="ROLLBACK_VERIFY_FAILED",
                original_failure=original_failure,
                manual_review_required=True,
                audit=audit)
        audit["rollback_status"] = "ROLLED_BACK"
        return RollbackOutcome(status="ROLLED_BACK",
                               original_failure=original_failure,
                               audit=audit)

    def _root_snapshot_manager(self):
        from .snapshot import SnapshotManager
        return SnapshotManager(self._root)

    def _verify_restored(self, snapshot: Snapshot,
                         resolved_target: str) -> bool:
        import hashlib
        manifest = snapshot.manifest
        backed = os.path.join(snapshot.dir, "target.bin")
        if os.path.exists(backed):
            if not os.path.exists(resolved_target):
                return False
            with open(backed, "rb") as a, \
                    open(resolved_target, "rb") as b:
                if a.read() != b.read():
                    return False
            # permissions
            perms_path = os.path.join(snapshot.dir, "perms.json")
            if os.path.exists(perms_path):
                with open(perms_path, "r", encoding="utf-8") as fh:
                    perms = json.load(fh)
                actual = os.stat(resolved_target).st_mode & 0o7777
                if actual != perms.get("mode", actual):
                    return False
            return True
        # snapshot captured ABSENT → target must be absent now
        return not os.path.exists(resolved_target)
