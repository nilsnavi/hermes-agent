"""Sprint 1.3.11 — durable cross-process lock + recovery (closes 1.3.10 T.D.)."""
from __future__ import annotations

import json
import os
import time

from .exceptions import LockConflict


class ReloadLock:
    def __init__(self, path: str, ttl_s: int = 300):
        self.path = path
        self.ttl = ttl_s
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def _read(self):
        try:
            with open(self.path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _write(self, rec):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(rec, f)
        os.replace(tmp, self.path)

    def acquire(self, service_id, txid, owner, nonce):
        cur = self._read()
        now = time.time()
        if cur and cur.get("service") == service_id and not self._is_stale(cur, now):
            raise LockConflict(f"lock held by tx {cur.get('txid')}")
        self._write({"service": service_id, "txid": txid, "owner": owner,
                     "nonce": nonce, "created": now, "ttl": self.ttl})
        return True

    def _is_stale(self, rec, now):
        return (now - rec.get("created", 0)) > rec.get("ttl", self.ttl)

    def release(self, service_id, txid):
        cur = self._read()
        if cur and cur.get("service") == service_id and cur.get("txid") == txid:
            try:
                os.remove(self.path)
            except OSError:
                pass
            return True
        return False

    def owner_alive(self, pid_str):
        try:
            pid = int(pid_str)
            os.kill(pid, 0)
        except (ValueError, OSError):
            return False
        return True