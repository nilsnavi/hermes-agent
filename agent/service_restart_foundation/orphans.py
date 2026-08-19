"""Sprint 1.3.12 — orphan detection (P0).

Any orphan -> RESTART_UNSAFE -> deny future autonomous restart.
Models: parent dies + child survives, cgroup member survives, forked worker
detached, stale pidfile, wrong socket owner, port owner remains.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DetectedOrphan:
    kind: str
    detail: str = ""


def orphan_scan(ctx: dict) -> list[DetectedOrphan]:
    """Scan a per-service observation context for orphan indicators (pure, no IO)."""
    findings: list[DetectedOrphan] = []

    old_pid = ctx.get("old_pid")

    children = ctx.get("children", ()) or ()
    if len(children) > 0:
        # child survives the parent's death -> orphan child
        findings.append(DetectedOrphan("orphan_child", f"children={list(children)}"))

    cgroup_members = ctx.get("cgroup_members", ()) or ()
    if len(cgroup_members) > 0:
        findings.append(DetectedOrphan("cgroup_member", f"members={list(cgroup_members)}"))

    forked_workers = ctx.get("forked_workers", ()) or ()
    if len(forked_workers) > 0:
        findings.append(DetectedOrphan("forked_worker", f"workers={list(forked_workers)}"))

    if ctx.get("stale_pidfile", False):
        findings.append(DetectedOrphan("stale_pidfile", "pidfile stale"))

    socket_owners = ctx.get("socket_owners", ()) or ()
    for owner in socket_owners:
        # a socket still owned by a non-current identity
        findings.append(DetectedOrphan("socket_owner", f"owner={owner}"))

    port_owners = ctx.get("port_owners", {}) or {}
    for port, owner in port_owners.items():
        findings.append(DetectedOrphan("port_owner", f"{port}->{owner}"))

    return findings


def has_orphan(ctx: dict) -> bool:
    return len(orphan_scan(ctx)) > 0


__all__ = ["DetectedOrphan", "has_orphan", "orphan_scan"]