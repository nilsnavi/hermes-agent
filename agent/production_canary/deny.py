"""Sprint 1.3.7 §23/§24/§32 — deny matrix + guarded adapter.

Decides allow/deny. Every deny is hard (adapter never called). System-control
families stay BLOCK even when the canary gate is enabled. The adapter counts
every real production call (for the attempt/mutation budget).
"""
from __future__ import annotations

from dataclasses import dataclass

from .capability import boundary_deny_class


@dataclass(frozen=True)
class DenyDecision:
    allowed: bool
    reason: str


class SystemControlDeny(Exception):
    """Any system-control action is permanently blocked (no adapter call)."""
    pass


SYSTEM_CONTROL_ACTIONS = frozenset({
    "SYSTEM_ACTION", "SERVICE_CONTROL", "PROCESS_CONTROL", "SIGNAL",
    "GATEWAY_RESTART", "SCHEDULER_MUTATION", "PROVIDER_MUTATION",
    "NETWORK_CONFIG", "FIREWALL", "DOCKER", "PACKAGE_MANAGEMENT",
    "SSH", "CRON", "KILL", "PKILL", "SYSTEMCTL",
})


def check_deny(*, target: str, operation: str, mode) -> DenyDecision:
    """Fail-closed deny decision. 'mode' = production canary Mode (or None)."""
    if operation in SYSTEM_CONTROL_ACTIONS or boundary_deny_class(operation):
        return DenyDecision(False, "system-control op permanently denied")
    target_l = target.lower()
    for deny in MY_TARGET_DENIES:
        if deny in target_l:
            return DenyDecision(False, f"deny target class: {deny}")
    if mode is None:
        return DenyDecision(False, "canary mode not active")
    return DenyDecision(True, "ok")


MY_TARGET_DENIES = (
    "config.yaml", "state.db", "/.env", "/.ssh/", "/etc/", "/run/",
    "/proc/", "/sys/", "cron/jobs", "scheduler", "inventory.json",
    "authorized_keys", "systemd", "gateway",
)


class ProductionAdapter:
    """The ONLY code path that touches the production target. Counts real calls."""

    def __init__(self) -> None:
        self.adapter_calls = 0

    def write(self, target: str, data: bytes) -> str:
        # atomic_write lives in .atomic_write; this adapter is the guarded boundary.
        from .atomic_write import atomic_write, content_hash
        self.adapter_calls += 1
        atomic_write(target, data, mode=0o600)
        return content_hash(data)
