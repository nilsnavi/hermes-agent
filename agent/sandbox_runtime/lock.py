"""Resource locking (Sprint 1.3.5 §14) — per-resource, bounded wait, stale recovery."""

from __future__ import annotations

import json
import os
import threading
import time
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .exceptions import LockConflict, LockStateAmbiguous


@dataclass
class ResourceLock:
    key: str
    path: str
    owner: str
    txid: str
    acquired_at: float
    ttl_s: float
    pid: int = 0
    process_start: Optional[str] = None
    process_nonce: Optional[str] = None
    resource_identity: Optional[str] = None
    _fd: Optional[int] = None


class StaleLockDisposition(str, Enum):
    NOT_STALE = "NOT_STALE"
    SAFE_TO_RELEASE = "SAFE_TO_RELEASE"
    LOCK_STATE_AMBIGUOUS = "LOCK_STATE_AMBIGUOUS"


def _process_start(pid: int) -> Optional[str]:
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as fh:
            return fh.read().split()[21]
    except (OSError, IndexError):
        return None


class ResourceLockManager:
    """File-based per-resource locks (no global lock).

    - lock key = resource identity + operation domain
    - bounded wait (wait_s); RESOURCE_BUSY/LockConflict otherwise
    - stale lock recovery: lock file older than TTL → recovered
    - owner identity + run_id + transaction_id + TTL recorded
    """

    def __init__(self, sandbox_root) -> None:
        self._dir = os.path.join(sandbox_root.root, ".locks")
        os.makedirs(self._dir, mode=0o700, exist_ok=True)
        self._held: dict = {}

    def _lock_path(self, key: str) -> str:
        import hashlib
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return os.path.join(self._dir, f"{digest}.lock")

    def acquire(self, key: str, owner: str, txid: str, ttl_s: float = 60.0,
                wait_s: float = 1.0, recover_stale: bool = True,
                sleep=None, process_nonce: Optional[str] = None,
                resource_identity: Optional[str] = None) -> ResourceLock:
        path = self._lock_path(key)
        process_nonce = process_nonce or secrets.token_hex(16)
        deadline = time.monotonic() + wait_s
        sleep_fn = sleep or time.sleep
        while True:
            # TTL is only a signal, never proof that release is safe.  The
            # caller must run assess_stale() with durable transaction and
            # reconciliation evidence before an explicit release.
            if recover_stale and os.path.exists(path):
                age = time.time() - os.path.getmtime(path)
                if age > ttl_s:
                    raise LockStateAmbiguous(
                        f"expired lock is ambiguous for {key} (age {age:.0f}s)")
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise LockConflict(f"resource busy: {key}")
                sleep_fn(min(0.05, max(0.005, deadline - time.monotonic())))
                continue
            except OSError:
                raise LockConflict(f"cannot lock {key}")
            meta = {
                "key": key, "owner": owner, "txid": txid,
                "transaction_id": txid, "pid": os.getpid(),
                "process_start": _process_start(os.getpid()),
                "process_nonce": process_nonce,
                "resource_identity": resource_identity or key,
                "acquired_at": time.time(), "ttl_s": ttl_s,
            }
            try:
                os.write(fd, json.dumps(meta).encode("utf-8"))
            except OSError:
                pass
            lock = ResourceLock(key=key, path=path, owner=owner, txid=txid,
                                acquired_at=time.time(), ttl_s=ttl_s,
                                pid=os.getpid(), process_start=meta["process_start"],
                                process_nonce=process_nonce,
                                resource_identity=resource_identity or key, _fd=fd)
            self._held[key] = lock
            return lock

    def release(self, lock: ResourceLock) -> None:
        if lock._fd is not None:
            try:
                os.close(lock._fd)
            except OSError:
                pass
            lock._fd = None
        # Never unlink a successor's lock: prove the complete durable owner
        # tuple immediately before removal.
        owned = False
        try:
            with open(lock.path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            owned = (meta.get("transaction_id", meta.get("txid")) == lock.txid and
                     meta.get("pid") == lock.pid and
                     meta.get("process_start") == lock.process_start and
                     meta.get("process_nonce") == lock.process_nonce and
                     meta.get("resource_identity") == lock.resource_identity)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            owned = False
        if owned:
            try:
                os.unlink(lock.path)
            except OSError:
                pass
        self._held.pop(lock.key, None)

    def is_held(self, key: str) -> bool:
        return key in self._held

    def proves_owner(self, lock: ResourceLock, *, txid: str, pid: int,
                     process_nonce: Optional[str],
                     resource_identity: str) -> bool:
        """Require the complete, non-reusable owner identity tuple."""
        return bool(lock.txid == txid and lock.pid == pid and
                    lock.process_start is not None and
                    lock.process_start == _process_start(pid) and
                    lock.process_nonce is not None and
                    lock.process_nonce == process_nonce and
                    lock.resource_identity == resource_identity)

    def assess_stale(self, key: str, *, owner_alive: Optional[bool],
                     transaction_active: Optional[bool],
                     resource_reconciled: bool) -> StaleLockDisposition:
        path = self._lock_path(key)
        if not os.path.exists(path):
            return StaleLockDisposition.NOT_STALE
        try:
            with open(path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            age = time.time() - float(meta["acquired_at"])
            expired = age > float(meta["ttl_s"])
            identity_complete = all(meta.get(k) is not None for k in
                                    ("pid", "process_nonce", "resource_identity"))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return StaleLockDisposition.LOCK_STATE_AMBIGUOUS
        if (expired and identity_complete and owner_alive is False and
                transaction_active is False and resource_reconciled):
            return StaleLockDisposition.SAFE_TO_RELEASE
        if not expired and owner_alive is True:
            return StaleLockDisposition.NOT_STALE
        return StaleLockDisposition.LOCK_STATE_AMBIGUOUS


class ProcessLocalLock:
    """Thread-safe in-process lock used by the pipeline to serialize
    concurrent mutation attempts on the same resource (belt over the
    file lock: atomic within one process)."""

    def __init__(self) -> None:
        self._locks: dict = {}
        self._lock = threading.Lock()

    def acquire(self, key: str, owner: str, txid: str,
                timeout_s: float = 1.0):
        deadline = time.monotonic() + timeout_s
        while True:
            with self._lock:
                holder = self._locks.get(key)
                if holder is None:
                    self._locks[key] = {"owner": owner, "txid": txid}
                    return {"key": key, "owner": owner, "txid": txid}
                if holder["txid"] == txid:
                    # same transaction re-enters → allowed (idempotent)
                    return {"key": key, "owner": owner, "txid": txid,
                            "reentrant": True}
            if time.monotonic() >= deadline:
                raise LockConflict(f"resource busy (process): {key}")
            time.sleep(0.01)

    def release(self, token) -> None:
        with self._lock:
            cur = self._locks.get(token["key"])
            if cur and cur["txid"] == token["txid"]:
                self._locks.pop(token["key"], None)
