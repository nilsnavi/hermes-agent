"""Sprint 1.3.8 — durable mutation budget + failure circuit breaker."""
from __future__ import annotations

import json
import os
import time

HOUR = 3600.0


class _Window(dict):
    pass


def _evict(items: list, now: float):
    # drop entries older than 1 hour
    return [t for t in items if now - t < HOUR]


class DurableBudget:
    """Per-profile + global durable budgets, fail-closed on BUDGET_EXCEEDED."""

    def __init__(self, path: str | None) -> None:
        self.path = path
        self.st = {
            "global_success": [], "global_attempt": [], "global_rollback": [],
            "per_profile": {},
            "circuit": {},  # profile_id -> {failures: n, consecutive_verify: n}
        }
        self._load() if path and os.path.exists(path) else None

    def _load(self):
        try:
            data = json.load(open(self.path))
            if isinstance(data, dict):
                self.st = data
        except (OSError, ValueError):
            self.st = {"global_success": [], "global_attempt": [], "global_rollback": [],
                       "per_profile": {}, "circuit": {}}

    def _save(self):
        if not self.path:
            return
        p = self.path
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.st, f)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, p)

    def _pp(self, pid: str) -> dict:
        return self.st["per_profile"].setdefault(pid, {
            "success": [], "attempt": [], "rollback": []})

    # ---- queries ----
    def circuit_state(self, pid: str) -> dict:
        return self.st["circuit"].get(pid, {"failures": 0, "consecutive_verify": 0,
                                            "consecutive_health": 0,
                                            "rollback_failed": 0,
                                            "unknown_outcome": 0})

    def budget_status(self, pid: str, spec) -> dict:
        now = time.time()
        g = {k: len(_evict(self.st[k], now)) for k in
             ("global_success", "global_attempt", "global_rollback")}
        p = {k: len(_evict(self._pp(pid)[k], now)) for k in
             ("success", "attempt", "rollback")}
        return {"global_success": g["global_success"], "global_attempt": g["global_attempt"],
                "global_rollback": g["global_rollback"],
                "profile_success": p["success"], "profile_attempt": p["attempt"],
                "profile_rollback": p["rollback"],
                "spec": {"global_success": spec, "profile_success": None}}

    def can_attempt(self, pid: str, spec, global_success_max: int) -> tuple[bool, str | None]:
        now = time.time()
        gs = len(_evict(self.st["global_success"], now))
        ga = len(_evict(self.st["global_attempt"], now))
        p = self._pp(pid)
        ps = len(_evict(p["success"], now))
        pa = len(_evict(p["attempt"], now))
        if gs >= global_success_max:
            return False, "global successful budget exhausted"
        if ga >= spec.max_attempts_per_hour + 8:  # conservative
            return False, "global attempt budget exhausted"
        if ps >= spec.max_successful_per_hour:
            return False, "profile successful budget exhausted"
        if pa >= spec.max_attempts_per_hour:
            return False, "profile attempt budget exhausted"
        return True, None

    def record_attempt(self, pid: str):
        now = time.time()
        self.st["global_attempt"].append(now)
        self._pp(pid)["attempt"].append(now)
        self._save()

    def record_success(self, pid: str):
        now = time.time()
        self.st["global_success"].append(now)
        self._pp(pid)["success"].append(now)
        self._save()

    def record_rollback(self, pid: str):
        now = time.time()
        self.st["global_rollback"].append(now)
        self._pp(pid)["rollback"].append(now)
        self._save()

    def bump(self, pid: str, key: str, n: int = 1):
        c = self.circuit_state(pid)
        c[key] = c.get(key, 0) + n
        self.st["circuit"][pid] = c
        self._save()

    def reset_circuit(self, pid: str):
        self.st["circuit"][pid] = {"failures": 0, "consecutive_verify": 0,
                                   "consecutive_health": 0, "rollback_failed": 0,
                                   "unknown_outcome": 0}
        self._save()

    def circuit_open(self, pid: str) -> bool:
        c = self.circuit_state(pid)
        return (c.get("failures", 0) >= 2 or c.get("consecutive_verify", 0) >= 2
                or c.get("consecutive_health", 0) >= 2 or c.get("rollback_failed", 0) >= 1
                or c.get("unknown_outcome", 0) >= 1)
