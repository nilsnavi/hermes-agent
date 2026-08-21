"""Sprint 1.3.13 — single aux service restart canary (post-restart verify).

Reuses the restart foundation pure models (PID transition, quiescence, orphan,
ports, post-start identity). Verify is read-only analysis of observation; it
never triggers a second restart.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..service_restart_foundation.models import ProcessIdentity
from ..service_restart_foundation.pid_transition import TransitionVerdict, validate_transition
from ..service_restart_foundation.quiescence import QuiescenceResult, evaluate_quiescence
from ..service_restart_foundation.orphans import orphan_scan
from ..service_restart_foundation.identity_after_start import verify_post_start_identity


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    reason: str = ""


def old_identity_gone(old: ProcessIdentity, current: ProcessIdentity | None) -> VerifyResult:
    """Old PID + old start identity must be gone. PID change alone is not enough."""
    if current is None:
        return VerifyResult(False, "no_current_process")
    if current.pid == old.pid and current.start_identity == old.start_identity:
        return VerifyResult(False, "old_identity_survives")
    return VerifyResult(True)


def new_identity_verified(old: ProcessIdentity, new: ProcessIdentity) -> VerifyResult:
    r = validate_transition(old, new)
    if r.verdict != TransitionVerdict.PASS:
        return VerifyResult(False, r.reason or "transition_fail")
    return VerifyResult(True)


def quiescence_check(obs: dict) -> VerifyResult:
    r = evaluate_quiescence(obs)
    if r.result != QuiescenceResult.QUIESCENT:
        return VerifyResult(False, r.result.value)
    return VerifyResult(True)


def orphan_check(ctx: dict) -> VerifyResult:
    findings = orphan_scan(ctx)
    if findings:
        return VerifyResult(False, findings[0].kind)
    return VerifyResult(True)


def port_check(owner_ok: bool, unexpected_minus: int = 0) -> VerifyResult:
    if not owner_ok:
        return VerifyResult(False, "port_wrong_owner")
    return VerifyResult(True)


def post_start_check(old: ProcessIdentity, new: ProcessIdentity,
                     expected_executable: str, expected_user: str,
                     expected_cgroup: str) -> VerifyResult:
    if not verify_post_start_identity(
            expected_executable=expected_executable,
            actual_executable=new.executable,
            expected_user=expected_user,
            actual_user=new.user,
            expected_cgroup=expected_cgroup or new.cgroup or "",
            actual_cgroup=new.cgroup or "",
            new_pid=new.pid,
    ):
        return VerifyResult(False, "post_start_identity_mismatch")
    return new_identity_verified(old, new)


__all__ = [
    "VerifyResult",
    "new_identity_verified",
    "old_identity_gone",
    "orphan_check",
    "port_check",
    "post_start_check",
    "quiescence_check",
]