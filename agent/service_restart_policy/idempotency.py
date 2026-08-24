"""Atomic durable claim-first semantic idempotency state machine."""
from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping

from ._durable import JsonTransaction, require_finite_time
from .models import RestartExecutionRequest

_STATES = {"CLAIMED", "EXECUTING", "COMMITTED", "FAILED_SAFE", "UNKNOWN_OUTCOME"}


def semantic_key(request: RestartExecutionRequest, context: object | None = None) -> str:
    if context is None:
        identity = request.transaction_id
    else:
        fields = (
            request.intent_id or request.transaction_id,
            getattr(context, "plan_hash", ""),
            getattr(context, "baseline_sha", ""),
            getattr(context, "config_digest", ""),
            getattr(context, "old_process_identity", ""),
        )
        identity = "\0".join(str(value) for value in fields)
    raw = f"RESTART\0{request.service_id}\0{request.profile_version}\0{identity}"
    return hashlib.sha256(raw.encode()).hexdigest()


class DurableIdempotencyStore:
    def __init__(self, root, *, clock_provenance: str = "legacy") -> None:
        self._tx = JsonTransaction(root, "idempotency")
        self.clock_provenance = clock_provenance

    def claim(
        self,
        key: str,
        now: float,
        owner_id: str | None = None,
        *,
        audit_wall: float | None = None,
    ) -> str:
        now = require_finite_time(now)
        owner = owner_id or "legacy-owner"

        def change(data):
            rec = data.get(key)
            if rec:
                state = rec.get("state", rec.get("outcome"))
                if state == "COMMITTED":
                    return "DUPLICATE" if owner_id is None else "ALREADY_COMMITTED"
                if state == "UNKNOWN_OUTCOME":
                    return "UNKNOWN_OUTCOME"
                if (
                    owner_id is not None
                    and rec.get("owner_id") == owner
                    and state in {"CLAIMED", "EXECUTING", "STARTED"}
                ):
                    return "CLAIMED_BY_ME"
                return "IN_FLIGHT" if owner_id is None else "CLAIMED_BY_OTHER"
            data[key] = {
                "state": "CLAIMED",
                "outcome": "CLAIMED",
                "owner_id": owner,
                "claimed_monotonic": now,
                "clock_provenance": self.clock_provenance,
                "audit_wall": audit_wall,
            }
            return "CLAIMED" if owner_id is None else "CLAIMED_BY_ME"

        return self._tx.update(change)

    def transition(
        self,
        key: str,
        owner_id: str,
        expected: set[str],
        state: str,
        now: float,
        *,
        outcome: str | None = None,
        result: Mapping | None = None,
        audit_wall: float | None = None,
    ) -> bool:
        if state not in _STATES:
            raise ValueError("invalid idempotency state")
        if state == "COMMITTED":
            raise PermissionError("COMMITTED is coordinator-owned")
        now = require_finite_time(now)

        def change(data):
            rec = data.get(key)
            if not isinstance(rec, dict):
                return False
            current = rec.get("state", rec.get("outcome"))
            if rec.get("owner_id") != owner_id or current not in expected:
                return False
            rec.update(
                {
                    "state": state,
                    "outcome": outcome or state,
                    "updated_monotonic": now,
                    "audit_wall": audit_wall,
                }
            )
            if result is not None:
                rec["result"] = dict(result)
            return True

        return self._tx.update(change)

    def set_phase(self, key: str, owner_id: str, phase: str, now: float) -> bool:
        now = require_finite_time(now)

        def change(data):
            rec = data.get(key)
            if (
                not isinstance(rec, dict)
                or rec.get("owner_id") != owner_id
                or rec.get("state") not in {"CLAIMED", "EXECUTING"}
            ):
                return False
            rec["transaction_phase"] = phase
            rec["updated_monotonic"] = now
            return True

        return self._tx.update(change)

    def commit(self, key: str, outcome: str, now: float, owner_id: str | None = None) -> None:
        if outcome == "COMMITTED":
            raise PermissionError("COMMITTED is coordinator-owned")
        now = require_finite_time(now)

        def change(data):
            rec = data.setdefault(key, {})
            if owner_id is not None and rec.get("owner_id") != owner_id:
                return False
            state = "COMMITTED" if outcome == "COMMITTED" else (
                "UNKNOWN_OUTCOME" if "UNKNOWN_OUTCOME" in outcome else "FAILED_SAFE"
            )
            rec.update(
                {
                    "state": state,
                    "outcome": outcome,
                    "completed_at": now,
                    "updated_monotonic": now,
                }
            )
            return True

        self._tx.update(change)

    def get(self, key: str):
        return self._tx.read().get(key)

    def wait_for_terminal(self, key: str, timeout: float = 2.0, poll: float = 0.005):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rec = self.get(key)
            if rec and rec.get("state", rec.get("outcome")) in {
                "COMMITTED", "FAILED_SAFE", "UNKNOWN_OUTCOME"
            }:
                return rec
            time.sleep(poll)
        return self.get(key)

    def coordinator_commit(
        self,
        runtime_owner: object,
        key: str,
        owner_id: str,
        now: float,
        *,
        result: Mapping | None = None,
        audit_wall: float | None = None,
    ) -> bool:
        from .runtime import LimitedRestartRuntime

        if (
            type(runtime_owner) is not LimitedRestartRuntime
            or runtime_owner.idempotency is not self
            or not runtime_owner._consume_commit_ready(self, key, owner_id)
        ):
            raise PermissionError("COMMITTED is coordinator-owned")
        now = require_finite_time(now)

        def change(data):
            rec = data.get(key)
            if (
                not isinstance(rec, dict)
                or rec.get("owner_id") != owner_id
                or rec.get("state") != "EXECUTING"
            ):
                return False
            rec.update({
                "state": "COMMITTED", "outcome": "COMMITTED",
                "updated_monotonic": now, "audit_wall": audit_wall,
            })
            if result is not None:
                rec["result"] = dict(result)
            return True

        return self._tx.update(change)


__all__ = ["DurableIdempotencyStore", "semantic_key"]
