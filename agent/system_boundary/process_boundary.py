"""Process boundary (Sprint 1.3.3 §27-§28).

Classes: CURRENT_PROCESS / CHILD_PROCESS / SIBLING_PROCESS /
FOREIGN_PROCESS / HERMES_GATEWAY / SYSTEM_PROCESS / UNKNOWN_PROCESS.

SELF-CONTROL PROHIBITION (P0, §28): Hermes gateway cannot restart /
stop / kill / pkill itself — including indirect execution.
"""

from dataclasses import dataclass
from typing import Optional


class ProcessClass:
    CURRENT_PROCESS = "CURRENT_PROCESS"
    CHILD_PROCESS = "CHILD_PROCESS"
    SIBLING_PROCESS = "SIBLING_PROCESS"
    FOREIGN_PROCESS = "FOREIGN_PROCESS"
    HERMES_GATEWAY = "HERMES_GATEWAY"
    SYSTEM_PROCESS = "SYSTEM_PROCESS"
    UNKNOWN_PROCESS = "UNKNOWN_PROCESS"


@dataclass(frozen=True)
class ProcessTarget:
    pid: Optional[int]
    name: str
    process_class: str
    is_self: bool = False


def classify_process_target(
    target: str,
    gateway_pids: Optional[set] = None,
    current_pid: Optional[int] = None,
) -> ProcessTarget:
    """Classify one process target (PID or name).

    ``gateway_pids`` = set of known Hermes gateway PIDs; targets that
    match are HERMES_GATEWAY + is_self=True (self-control forbidden).
    """
    gateway_pids = gateway_pids or set()
    raw = str(target).strip()
    pid = None
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        pass

    if pid is not None:
        if pid == current_pid:
            return ProcessTarget(pid, raw, ProcessClass.CURRENT_PROCESS,
                                 is_self=True)
        if pid in gateway_pids:
            return ProcessTarget(pid, raw, ProcessClass.HERMES_GATEWAY,
                                 is_self=True)
        if pid <= 0:
            return ProcessTarget(pid, raw, ProcessClass.UNKNOWN_PROCESS)
        return ProcessTarget(pid, raw, ProcessClass.FOREIGN_PROCESS)

    low = raw.lower()
    if "hermes-gateway" in low:
        return ProcessTarget(None, raw, ProcessClass.HERMES_GATEWAY,
                             is_self=True)
    if low in ("init", "systemd", "kernel", "kthreadd"):
        return ProcessTarget(None, raw, ProcessClass.SYSTEM_PROCESS)
    return ProcessTarget(None, raw, ProcessClass.UNKNOWN_PROCESS)


__all__ = [
    "ProcessClass",
    "ProcessTarget",
    "classify_process_target",
]
