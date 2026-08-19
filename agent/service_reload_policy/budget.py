"""Sprint 1.3.11 — durable global+per-service budget."""
from __future__ import annotations

import json
import os
import time

HOUR = 3600.0


class ReloadBudget:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._d = self._read()

    def _read(self):
        try:
            with open(self.path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"success": [], "attempts": []}

    def _write(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._d, f)
        os.replace(tmp, self.path)

    @staticmethod
    def _fresh(times):
        now = time.time()
        return [x for x in times if (now - x) < HOUR]

    def can_attempt(self):
        return len(self._fresh(self._d["attempts"])) < 8

    def can_success(self):
        return len(self._fresh(self._d["success"])) < 5

    def reserve_attempt(self):
        self._d["attempts"].append(time.time())
        self._write()

    def record_success(self):
        self._d["success"].append(time.time())
        self._write()

    def release_reservation(self):
        if self._d["attempts"]:
            self._d["attempts"] = self._d["attempts"][:-1]
            self._write()