"""Sprint 1.3.16 — process/boot/host provenance for recovery ownership proof.

PID reuse (same PID, different process-start identity) must be treated as a
DIFFERENT process.  Host identity binds recovery claims to one host; a foreign
host may inspect but cannot silently assume ownership.
"""
from __future__ import annotations

import hashlib
import os
import socket
import time


def _proc_start_identity(pid: int) -> str:
    """Durable process-start identity from /proc/<pid>/stat starttime field.
    Falls back to a process-global token if /proc is unavailable."""
    try:
        with open(f"/proc/{pid}/stat", "r") as fh:
            tail = fh.read().rsplit(")", 1)[1].split()
        # field 22 = starttime (jiffies) of the process
        return f"pid:{pid}-start:{tail[19] if len(tail) > 19 else 'na'}"
    except Exception:
        return f"pid:{pid}-fallback:{time.time_ns()}"


class Provenance:
    """Authority-grade provenance for recovery claims."""

    def __init__(self, host_identity: str | None = None,
                 runtime_identity: str = "multi-service-recovery",
                 pid: int | None = None) -> None:
        self.pid = pid if pid is not None else os.getpid()
        self.process_start_identity = _proc_start_identity(self.pid)
        self.host_identity = host_identity or socket.gethostname()
        self.runtime_identity = runtime_identity

    def digest(self) -> str:
        raw = "|".join([str(self.pid), self.process_start_identity,
                        self.host_identity, self.runtime_identity])
        return hashlib.sha256(raw.encode()).hexdigest()

    def same_host(self, other_host: str) -> bool:
        return self.host_identity == other_host

    @classmethod
    def same_process(cls, pid: int, stored_start: str) -> bool:
        return _proc_start_identity(pid) == stored_start


def same_process(pid: int, stored_start: str) -> bool:
    return _proc_start_identity(pid) == stored_start


__all__ = ["Provenance", "same_process", "_proc_start_identity"]