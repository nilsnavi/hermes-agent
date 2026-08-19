"""Sprint 1.3.11 — limited service reload policy decision engine (fail-closed)."""
from __future__ import annotations

from .breaker import KillSwitch, ReloadBreaker
from .budget import ReloadBudget
from .exceptions import (ApprovalInvalid, BreakerOpen, BudgetExceeded,
                         OperationDenied, PolicyDenied)
from .models import Op
from .registry import ReloadRegistry


def effective_action_is_reload(exec_reload: str) -> bool:
    """Only proven reload semantics; restart-like/unknown -> False."""
    s = (exec_reload or "").strip()
    low = s.lower()
    for bad in ("restart", "reload-or-restart", "stop", "start", "pkill", "killall"):
        if bad in low:
            return False
    if "hup" in low or "reload" in low or "signal" in low:
        return True
    return False  # unknown semantics


DENIED_OPS = {Op.RESTART, Op.STOP, Op.START}


def gate(*, registered: bool, profile, chk, approval_valid: bool,
         budget: ReloadBudget, breaker: ReloadBreaker, kill: KillSwitch,
         op: str = "RELOAD", consumer_ok: bool = True, blast_ok: bool = True) -> str:
    """Return outcome (reason) or None if all gates pass."""
    if op not in ("RELOAD", Op.RELOAD.value):
        return "OPERATION_DENIED"
    if kill.is_killed():
        return "POLICY_KILLED"
    if not registered:
        return "SERVICE_NOT_REGISTERED"
    if not profile.enabled:
        return "PROFILE_DISABLED"
    if breaker.is_open(profile.service_id):
        return "BREAKER_OPEN"
    if not consumer_ok:
        return "CONSUMER_DENIED"
    if not blast_ok:
        return "BLAST_RADIUS_TOO_HIGH"
    if not budget.can_attempt():
        return "BUDGET_EXCEEDED"
    if not approval_valid:
        return "APPROVAL_INVALID"
    return None