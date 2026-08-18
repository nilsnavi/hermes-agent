"""Health gate (Sprint 1.3.5 §20) — post-verification sandbox health."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class HealthReport:
    ok: bool
    checks: List[Tuple[str, bool]] = field(default_factory=list)


class SandboxHealth:
    def __init__(self, root: str, exclude_txid: str | None = None) -> None:
        self.root = root
        self.exclude_txid = exclude_txid

    def check(self) -> HealthReport:
        checks: List[Tuple[str, bool]] = []
        # filesystem writable
        checks.append(("filesystem_writable",
                       os.path.isdir(self.root) and
                       os.access(self.root, os.W_OK)))
        # sandbox root exists
        checks.append(("sandbox_root_exists", os.path.isdir(self.root)))
        # manifest consistent (snapshots dir is a dir)
        snaps = os.path.join(self.root, ".snapshots")
        checks.append(("snapshot_dir_ok",
                       os.path.isdir(snaps) if os.path.exists(snaps) else True))
        # no orphan transactions
        txn = os.path.join(self.root, ".txn")
        orphans = 0
        if os.path.isdir(txn):
            for name in os.listdir(txn):
                if name.endswith(".json") and not name.startswith("done"):
                    orphans += 1
        checks.append(("no_orphan_transactions", orphans == 0))
        # no leaked processes / unexpected service state
        svc = os.path.join(self.root, ".service")
        leak = False
        if os.path.isdir(svc):
            state_path = os.path.join(svc, "state.json")
            if os.path.exists(state_path):
                try:
                    with open(state_path, "r", encoding="utf-8") as fh:
                        st = json.load(fh)
                    pid = st.get("pid")
                    owned = st.get("owned", True)
                    if owned and pid and not os.path.exists(f"/proc/{pid}"):
                        # declared pid not running → stale, not a leak
                        pass
                    if not owned:
                        leak = True
                except (json.JSONDecodeError, OSError):
                    leak = True
        checks.append(("no_leaked_processes", not leak))
        # no lock leak — the current transaction's own lock is expected
        locks = os.path.join(self.root, ".locks")
        leaked = []
        if os.path.isdir(locks):
            for name in os.listdir(locks):
                if not name.endswith(".lock"):
                    continue
                owner_txid = None
                try:
                    with open(os.path.join(locks, name), "r",
                              encoding="utf-8") as fh:
                        meta = json.load(fh)
                    owner_txid = meta.get("txid")
                except (json.JSONDecodeError, OSError):
                    pass
                if self.exclude_txid is None or owner_txid != self.exclude_txid:
                    leaked.append(name)
        checks.append(("no_lock_leak", len(leaked) == 0))
        ok = all(c for _, c in checks)
        return HealthReport(ok=ok, checks=checks)


def check_sandbox_health(sandbox_root,
                         exclude_txid: str | None = None) -> HealthReport:
    return SandboxHealth(sandbox_root.root, exclude_txid=exclude_txid).check()
