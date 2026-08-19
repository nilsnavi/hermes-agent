"""Sprint 1.3.11 — per-service circuit breaker + global kill-switch (durable)."""
from __future__ import annotations

import json
import os


class ReloadBreaker:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._d = self._read()

    def _read(self):
        try:
            with open(self.path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"consecutive_verify": {}, "consecutive_health": {},
                    "rollback_fail": {}, "unknown": {}, "open": {}}

    def _write(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._d, f)
        os.replace(tmp, self.path)

    def is_open(self, sid):
        return self._d["open"].get(sid, False)

    def note_verify_fail(self, sid):
        self._d["consecutive_verify"][sid] = self._d["consecutive_verify"].get(sid, 0) + 1
        if self._d["consecutive_verify"][sid] >= 2:
            self._open(sid, "consecutive_verify_fail")
        self._write()

    def note_health_fail(self, sid):
        self._d["consecutive_health"][sid] = self._d["consecutive_health"].get(sid, 0) + 1
        if self._d["consecutive_health"][sid] >= 2:
            self._open(sid, "consecutive_health_fail")
        self._write()

    def note_rollback_fail(self, sid):
        self._open(sid, "rollback_fail")

    def note_unknown(self, sid):
        self._open(sid, "unknown_outcome")

    def note_success(self, sid):
        self._d["consecutive_verify"][sid] = 0
        self._d["consecutive_health"][sid] = 0
        self._write()

    def _open(self, sid, reason):
        self._d["open"][sid] = reason

    def reset(self, sid):
        self._d["open"][sid] = False
        self._write()


class KillSwitch:
    def __init__(self, path: str):
        self.path = path

    @staticmethod
    def _read(path):
        try:
            with open(path) as f:
                return f.read().strip() == "on"
        except OSError:
            return False

    def is_killed(self):
        return self._read(self.path)