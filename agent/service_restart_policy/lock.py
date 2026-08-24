"""Live-owner-aware PID+start+transaction+nonce service lease."""
from __future__ import annotations

import os
import socket
from collections.abc import Callable
from pathlib import Path

from ._durable import DurableStateCorrupt, JsonTransaction, require_finite_time


def _linux_process_start(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        comm_end = raw.rfind(")")
        if comm_end < 0:
            return None
        fields_after_comm = raw[comm_end + 1 :].split()
        return fields_after_comm[19]
    except (OSError, IndexError):
        return None


def _linux_owner_liveness(pid: int, expected_start: str) -> str:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError):
        return "DEAD"
    except OSError:
        return "UNKNOWN"
    comm_end = raw.rfind(")")
    if comm_end < 0:
        return "UNKNOWN"
    fields_after_comm = raw[comm_end + 1 :].split()
    if len(fields_after_comm) <= 19:
        return "UNKNOWN"
    return "ALIVE" if fields_after_comm[19] == expected_start else "REUSED"


class HardenedServiceLock:
    def __init__(
        self,
        root,
        process_start: Callable[[int], str | None] = _linux_process_start,
        ttl: float = 30.0,
        max_clock_drift: float = 5.0,
        *,
        owner_liveness: Callable[[int, str], str] | None = None,
        transaction_active: Callable[[str, str], bool | None] | None = None,
        recovery_allows_takeover: Callable[[dict, str], bool] | None = None,
        host_identity: str | None = None,
    ) -> None:
        self.root = root
        self.process_start = process_start
        self.ttl = require_finite_time(ttl)
        self.max_clock_drift = require_finite_time(max_clock_drift)
        if self.ttl <= 0 or self.max_clock_drift < 0:
            raise ValueError("lock timing bounds are invalid")
        self.owner_liveness = (
            _linux_owner_liveness
            if owner_liveness is None and process_start is _linux_process_start
            else owner_liveness
        )
        self.transaction_active = transaction_active or (lambda service_id, txid: False)
        self.recovery_allows_takeover = recovery_allows_takeover or (
            lambda record, classification: classification in {"OWNER_DEAD", "PID_REUSED"}
        )
        self.host_identity = host_identity or socket.gethostname()

    def _tx(self, service_id: str) -> JsonTransaction:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in service_id)
        return JsonTransaction(self.root, f"service-lock-{safe}")

    def _classification(self, pid: int, expected_start: str) -> str:
        if self.owner_liveness is not None:
            status = self.owner_liveness(pid, expected_start)
            if status not in {"ALIVE", "DEAD", "UNKNOWN", "REUSED"}:
                return "UNKNOWN"
            return status
        current_start = self.process_start(pid)
        if current_start is None:
            return "DEAD"
        if current_start == expected_start:
            return "ALIVE"
        return "REUSED"

    def acquire(
        self,
        service_id: str,
        pid: int,
        start: str,
        nonce: str,
        now: float,
        transaction_id: str | None = None,
    ) -> bool:
        now = require_finite_time(now)
        txid = transaction_id or nonce
        if (
            pid <= 0
            or not start
            or not nonce
            or not txid
            or self.process_start(pid) != start
        ):
            return False

        def change(data):
            rec = data.get("holder")
            if rec is not None:
                if not isinstance(rec, dict):
                    raise DurableStateCorrupt("invalid lock holder")
                exact_owner = (
                    rec.get("pid"), rec.get("start"), rec.get("nonce"), rec.get("transaction_id")
                ) == (pid, start, nonce, txid)
                if exact_owner:
                    return True
                try:
                    deadline = require_finite_time(
                        rec.get("lease_deadline", rec.get("expires_at"))
                    )
                    created = require_finite_time(
                        rec.get("lease_created", rec.get("acquired_at"))
                    )
                except ValueError as exc:
                    raise DurableStateCorrupt("invalid lock timestamp") from exc
                if now < created - self.max_clock_drift:
                    return False
                if now < deadline:
                    return False
                classification = self._classification(
                    int(rec.get("pid", -1)), str(rec.get("start", ""))
                )
                if classification == "ALIVE":
                    return False
                if classification == "UNKNOWN":
                    return False
                active = self.transaction_active(
                    service_id, str(rec.get("transaction_id", ""))
                )
                if active is not False:
                    return False
                recovery_class = (
                    "OWNER_DEAD" if classification == "DEAD" else "PID_REUSED"
                )
                if not self.recovery_allows_takeover(rec, recovery_class):
                    return False
            data["holder"] = {
                "service_id": service_id,
                "transaction_id": txid,
                "owner_pid": pid,
                "owner_process_start_identity": start,
                "pid": pid,
                "start": start,
                "nonce": nonce,
                "lease_created": now,
                "lease_deadline": now + self.ttl,
                "acquired_at": now,
                "expires_at": now + self.ttl,
                "heartbeat": 0,
                "version": 1,
                "host_identity": self.host_identity,
            }
            return True

        return self._tx(service_id).update(change)

    def renew(
        self,
        service_id: str,
        transaction_id: str,
        pid: int,
        start: str,
        nonce: str,
        now: float,
    ) -> bool:
        now = require_finite_time(now)
        # Live-owner proof: the process actually performing the renewal is the
        # only acceptable owner.  ``os.getpid()`` comes from the trusted process
        # inspector (the OS), so a caller cannot override it by replaying the
        # lock record's pid/start/nonce.
        current_pid = os.getpid()

        def change(data):
            rec = data.get("holder")
            if not isinstance(rec, dict) or not self._matches(
                rec, transaction_id, pid, start, nonce
            ):
                return False
            # The renewing process must BE the recorded owner (not merely pass
            # the owner's tuple read from the lock file).
            if int(rec.get("pid", -1)) != current_pid:
                return False
            # Fresh liveness verification of the actual current process against
            # the stored start identity.  FAIL-CLOSED on UNKNOWN.
            if self._classification(current_pid, str(rec.get("start", ""))) != "ALIVE":
                return False
            rec["lease_deadline"] = now + self.ttl
            rec["expires_at"] = now + self.ttl
            rec["heartbeat"] = int(rec.get("heartbeat", 0)) + 1
            rec["version"] = int(rec.get("version", 1)) + 1
            return True

        return self._tx(service_id).update(change)

    @staticmethod
    def _matches(rec: dict, transaction_id: str, pid: int, start: str, nonce: str) -> bool:
        return (
            rec.get("transaction_id"), rec.get("pid"), rec.get("start"), rec.get("nonce")
        ) == (transaction_id, pid, start, nonce)

    def owns(
        self,
        service_id: str,
        transaction_id: str,
        pid: int,
        start: str,
        nonce: str,
        now: float,
    ) -> bool:
        now = require_finite_time(now)
        rec = self.holder(service_id)
        if not isinstance(rec, dict) or not self._matches(rec, transaction_id, pid, start, nonce):
            return False
        try:
            deadline = require_finite_time(rec.get("lease_deadline"))
        except ValueError:
            return False
        return now <= deadline and self.process_start(pid) == start

    def release(
        self,
        service_id: str,
        pid: int,
        start: str,
        nonce: str,
        transaction_id: str | None = None,
    ) -> bool:
        txid = transaction_id or nonce

        def change(data):
            rec = data.get("holder")
            if rec is None:
                return True
            if not isinstance(rec, dict) or not self._matches(rec, txid, pid, start, nonce):
                return False
            data.pop("holder", None)
            return True

        return self._tx(service_id).update(change)

    def holder(self, service_id: str):
        return self._tx(service_id).read().get("holder")


__all__ = ["HardenedServiceLock"]
