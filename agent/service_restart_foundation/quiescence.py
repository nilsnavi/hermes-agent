"""Sprint 1.3.12 — quiescence gate between stop and start.

Only QUIESCENT allows a future start. Pure observation; no mutation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class QuiescenceResult(Enum):
    QUIESCENT = "QUIESCENT"
    NOT_QUIESCENT = "NOT_QUIESCENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class QuiescenceCheck:
    result: QuiescenceResult
    reasons: tuple = field(default_factory=tuple)


def evaluate_quiescence(obs: dict) -> QuiescenceCheck:
    """Evaluate quiescence from a pure observation dict (family==_obs fixture)."""
    reasons: list[str] = []

    old_pid_present = obs.get("old_pid_present", False)
    if old_pid_present is None:
        return QuiescenceCheck(QuiescenceResult.UNKNOWN, ("old_state_unknown",))

    if old_pid_present:
        reasons.append("old_pid_present")
    if obs.get("old_start_identity_present", False):
        reasons.append("old_start_identity_present")

    children = obs.get("children", ()) or ()
    if len(children) > 0:
        reasons.append("children")

    orphan_workers = obs.get("orphan_workers", ()) or ()
    if len(orphan_workers) > 0:
        reasons.append("orphan_workers")

    cgroup_members = obs.get("cgroup_members", ()) or ()
    if len(cgroup_members) > 0:
        reasons.append("cgroup_members")

    if obs.get("stale_pidfile", False):
        reasons.append("stale_pidfile")

    port_owners = obs.get("port_owners", {}) or {}
    if len(port_owners) > 0:
        reasons.append("port_owners")

    unit_state = obs.get("unit_state", "inactive")
    if unit_state not in ("inactive", "dead"):
        reasons.append(f"unit_state={unit_state}")

    if reasons:
        return QuiescenceCheck(QuiescenceResult.NOT_QUIESCENT, tuple(reasons))
    return QuiescenceCheck(QuiescenceResult.QUIESCENT)


def quiescent(obs: dict) -> bool:
    return evaluate_quiescence(obs).result == QuiescenceResult.QUIESCENT


__all__ = ["QuiescenceCheck", "QuiescenceResult", "evaluate_quiescence", "quiescent"]