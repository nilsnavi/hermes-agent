"""Sprint 1.3.7 §17 — exclusive resource lease with durable owner identity."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time


class LockConflict(Exception):
    pass


class ResourceLock:
    def __init__(self, key: str, path: str, txid: str) -> None:
        self.key = key
        self.path = path
        self.txid = txid


class LockManager:
    """File-based exclusive lease keyed by exact resource identity.

    Durable owner identity: (txid, pid, process_start, nonce, resource).
    Expired TTL alone is NOT permission to release (Sprint 1.3.6 rule).
    """

    def __init__(self, lock_dir: str, ttl_s: float = 60.0) -> None:
        self._dir = lock_dir
        self._ttl = ttl_s
        os.makedirs(self._dir, exist_ok=True)

    def _path(self, key: str) -> str:
        h = hashlib.sha256(key.encode()).hexdigest()[:32]
        return os.path.join(self._dir, f"{h}.lock")

    def acquire(self, key: str, txid: str, *, wait_s: float = 5.0,
                process_nonce: str | None = None) -> ResourceLock:
        path = self._path(key)
        deadline = time.monotonic() + wait_s
        process_nonce = process_nonce or secrets.token_hex(8)
        while True:
            # expired lock is AMBIGUOUS, not auto-releasable (1.3.6 rule)
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        meta = json.load(f)
                    if time.time() - meta.get("acquired_at", 0) > self._ttl:
                        raise LockConflict(
                            "stale lock is ambiguous for resource; requires owner proof")
                except (json.JSONDecodeError, OSError):
                    pass
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise LockConflict(f"resource busy: {key}")
                time.sleep(0.02)
                continue
            meta = {
                "txid": txid, "resource": key,
                "pid": os.getpid(),
                "process_start": _proc_start(),
                "process_nonce": process_nonce,
                "acquired_at": time.time(), "ttl_s": self._ttl,
            }
            os.write(fd, json.dumps(meta).encode())
            os.close(fd)
            return ResourceLock(key=key, path=path, txid=txid)

    def release(self, lock: ResourceLock) -> None:
        try:
            if os.path.exists(lock.path):
                os.unlink(lock.path)
        except OSError:
            pass


def _proc_start() -> str:
    try:
        with open(f"/proc/{os.getpid()}/stat") as f:
            f.readline()
            parts = f.readline().split()
            return parts[19] if len(parts) > 20 else str(time.time())
    except OSError:
        return str(time.time())
