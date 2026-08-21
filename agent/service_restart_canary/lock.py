"""Sprint 1.3.13 — single aux service restart canary (durable lock).

Cross-process per-service lock (owner PID + start identity + nonce + TTL).
same-service active writers <= 1. Stale lock -> safe recovery only.
File-backed so multiple subprocesses agree on the single holder.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


class DurableServiceLock:
    def __init__(self, store_dir: str | Path,
                 service_id: str = "hermes-aux-canary",
                 ttl: float = 30.0) -> None:
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"lock-{service_id}.json"
        self._service = service_id
        self._ttl = ttl

    def _read(self) -> dict | None:
        if not self._path.exists():
            return None
        try:
            return json.loads(self._path.read_text())
        except Exception:
            return None

    def acquire(self, owner_pid: int, owner_start: str, nonce: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        cur = self._read()
        if cur and not self._is_stale(cur, now):
            return False  # held by active writer
        payload = {
            "service_id": self._service,
            "owner_pid": owner_pid,
            "owner_start": owner_start,
            "nonce": nonce,
            "expires_at": now + self._ttl,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, self._path)
        return True

    def _is_stale(self, rec: dict, now: float) -> bool:
        return now > float(rec.get("expires_at", 0))

    def release(self, owner_pid: int, nonce: str) -> bool:
        cur = self._read()
        if not cur:
            return True
        if int(cur.get("owner_pid", -1)) == owner_pid and cur.get("nonce") == nonce:
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass
            return True
        return False

    def holder(self) -> dict | None:
        return self._read()

    def stale(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        cur = self._read()
        return bool(cur is None or self._is_stale(cur, now))


__all__ = ["DurableServiceLock"]