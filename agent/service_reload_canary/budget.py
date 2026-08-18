"""Sprint 1.3.10 — durable live reload budget."""
from __future__ import annotations

import json
import os
import time

MAX_TOTAL_ATTEMPTS = 3
MAX_SUCCESSFUL = 2
MAX_ROLLBACK = 1


class ReloadBudget:
    def __init__(self, path: str | None = None):
        self.path = path
        self.attempts = 0
        self.success = 0
        self.rollbacks = 0
        self._load()

    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            d = json.load(open(self.path))
            self.attempts = d.get("attempts", 0)
            self.success = d.get("success", 0)
            self.rollbacks = d.get("rollbacks", 0)
        except Exception:
            pass

    def _save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        json.dump({"attempts": self.attempts, "success": self.success,
                   "rollbacks": self.rollbacks}, open(self.path, "w"))

    def can_attempt(self) -> bool:
        return self.attempts < MAX_TOTAL_ATTEMPTS

    def record_attempt(self):
        self.attempts += 1
        self._save()

    def record_success(self):
        self.success += 1
        self._save()

    def record_rollback(self):
        self.rollbacks += 1
        self._save()
