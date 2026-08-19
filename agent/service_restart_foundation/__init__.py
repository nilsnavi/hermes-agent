"""Sprint 1.3.12 — Controlled Auxiliary Service Restart Foundation (shadow/fake only).

PRODUCTION RESTART EXECUTION = 0 in 1.3.12. This package models, plans and
evaluates restart semantics (PID transition, quiescence, orphans, ports,
stop/start contracts, post-start identity, blast radius, risk, rollback,
recovery) without ever mutating production: every execution path is hard-blocked
by the P0 execution guard.

RESTART AUTHORITY IS SEPARATE FROM RELOAD AUTHORITY. Nothing here derives a
restart right from reload rights.
"""
from __future__ import annotations

from .exceptions import (
    OrphanRisk,
    RestartDisabled,
    RestartFoundationError,
    RestartNotAdmitted,
    RestartPlanInvalid,
)
from .models import (
    ProcessIdentity,
    RestartTransition,
    StartState,
    StopState,
)

__all__ = [
    "OrphanRisk",
    "ProcessIdentity",
    "RestartDisabled",
    "RestartFoundationError",
    "RestartNotAdmitted",
    "RestartPlanInvalid",
    "RestartTransition",
    "StartState",
    "StopState",
]