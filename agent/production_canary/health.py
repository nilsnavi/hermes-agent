"""Sprint 1.3.7 §19 — health gate before/after a canary mutation.

Verifies production invariants around the mutation. A canary mutation must
NOT require a gateway restart; any unexpected production drift -> health fail
-> rollback. Injectable checks for testability; live checks opened lazily.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class HealthSnapshot:
    gateway_pid: int | None = None
    nrestarts: int | None = None
    active_state: str | None = None
    sub_state: str | None = None
    scheduler_hash: str | None = None
    provider_hash: str | None = None
    config_hash: str | None = None
    db_quick_ok: bool = True
    canary_sha: str | None = None


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


_DB = os.path.expanduser("~/.hermes/state.db")
_CONFIG = os.path.expanduser("~/.hermes/config.yaml")
_INVENTORY = os.path.expanduser("~/.hermes/infra/inventory.json")
_JOBS = os.path.expanduser("~/.hermes/cron/jobs.json")


def _db_quick_ok() -> bool:
    """Bounded lightweight DB health probe (fast, non-blocking under WAL load).

    A full PRAGMA quick_check over the live multi-hundred-MB WAL DB is slow and
    non-deterministic under an active writer (Sprint 1.3.6.1 audit). The
    per-mutation health gate checks read-ability (journal mode + schema probe)
    within a hard wall-clock bound; a full integrity/quick check is run at
    sprint close on a consistent read-only copy (Sprint 1.3.7 §35).
    """
    import signal
    if not os.path.exists(_DB):
        return False
    out = {"ok": False}

    def _run():
        try:
            c = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=1,
                                isolation_level=None)
            try:
                c.execute("PRAGMA query_only=ON")
                c.execute("PRAGMA busy_timeout=1200")
                jm = c.execute("PRAGMA journal_mode").fetchone()[0]
                sv = c.execute("PRAGMA schema_version").fetchone()[0]
                out["ok"] = (jm in ("wal", "delete", "truncate", "persist", "off")
                             and isinstance(sv, int) and sv >= 0)
            finally:
                c.close()
        except Exception:
            out["ok"] = False

    timed = {"v": False}
    def _boom(*_a):
        timed["v"] = True
        raise TimeoutError("db health probe timed out")
    old = None
    if hasattr(signal, "SIGALRM"):
        old = signal.signal(signal.SIGALRM, _boom)
        signal.alarm(2)
    try:
        _run()
    except Exception:
        pass
    finally:
        if old is not None:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
    return False if timed["v"] else out["ok"]


def _scheduler_hash() -> str | None:
    try:
        jobs = json.load(open(_JOBS))
        ids = sorted(j["id"] for j in (jobs if isinstance(jobs, list) else jobs.get("jobs", [])))
        return hashlib.sha256("\n".join(ids).encode()).hexdigest()
    except Exception:
        return None


def _sha_or_none(path: str) -> str | None:
    try:
        return sha256_file(path)
    except OSError:
        return None


def capture(canary_path: str | None = None) -> HealthSnapshot:
    db_ok = _db_quick_ok()
    snap = HealthSnapshot(
        scheduler_hash=_scheduler_hash(),
        provider_hash=_sha_or_none(_INVENTORY),
        config_hash=_sha_or_none(_CONFIG),
        db_quick_ok=db_ok,
        canary_sha=_sha_or_none(canary_path) if canary_path else None,
    )
    # gateway via systemctl (read-only); tolerate absence in sandbox
    try:
        import subprocess
        r = subprocess.run(
            ["systemctl", "--user", "show", "hermes-gateway.service",
             "-p", "MainPID", "-p", "NRestarts", "-p", "ActiveState", "-p", "SubState"],
            capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith("MainPID="):
                snap = HealthSnapshot(**{**snap.__dict__, "gateway_pid": int(line.split("=",1)[1] or 0) or None})
            elif line.startswith("NRestarts="):
                snap = HealthSnapshot(**{**snap.__dict__, "nrestarts": int(line.split("=",1)[1])})
            elif line.startswith("ActiveState="):
                snap = HealthSnapshot(**{**snap.__dict__, "active_state": line.split("=",1)[1]})
            elif line.startswith("SubState="):
                snap = HealthSnapshot(**{**snap.__dict__, "sub_state": line.split("=",1)[1]})
    except Exception:
        pass
    return snap


def compare_before_after(before: HealthSnapshot, after: HealthSnapshot,
                         *, require_gateway_stable: bool = True) -> list[str]:
    errors: list[str] = []
    if require_gateway_stable:
        if after.gateway_pid != before.gateway_pid:
            errors.append("gateway PID changed")
        if after.nrestarts != before.nrestarts:
            errors.append("gateway NRestarts changed")
        if after.active_state != before.active_state or after.sub_state != before.sub_state:
            errors.append("gateway state changed")
    if after.scheduler_hash != before.scheduler_hash:
        errors.append("scheduler identity changed")
    if after.provider_hash != before.provider_hash:
        errors.append("provider inventory changed")
    if after.config_hash != before.config_hash:
        errors.append("production config changed")
    if not after.db_quick_ok:
        errors.append("state.db quick_check failed")
    return errors
