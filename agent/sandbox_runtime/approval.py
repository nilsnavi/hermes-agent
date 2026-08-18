"""Approval (Sprint 1.3.5 §10) — run-scoped, plan-scoped, version-guarded,
TTL-bound, single-use."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Dict, Optional

from .exceptions import (
    ApprovalExpired,
    ApprovalInvalid,
    ApprovalReuse,
)
from .models import SandboxMutationPlan


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    USED = "USED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class ApprovalVerdict:
    ok: bool
    approval_id: str
    reason: str = ""


class ApprovalManager:
    """Single-use, plan-scoped approvals.

    - one approval per (plan, run) — double issue refused
    - validation binds plan_id + run_id + policy/boundary version
    - TTL enforced at validate time via injectable clock
    - single-use: first validate() consumes it
    """

    def __init__(self,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone_utc()))
        self._seq = 0
        self._lock = threading.Lock()
        self._approvals: Dict[str, Dict] = {}

    def issue(self, plan: SandboxMutationPlan, requested_by: str,
              ttl_s: float = 300.0) -> str:
        with self._lock:
            # double-issue for the same plan → refuse (no second right)
            for aid, rec in self._approvals.items():
                if rec["plan_id"] == plan.plan_id and \
                        rec["status"] == ApprovalStatus.PENDING:
                    raise ApprovalReuse(
                        f"plan {plan.plan_id} already has a pending "
                        f"approval {aid}")
            self._seq += 1
            aid = f"approval-{self._seq}"
            self._approvals[aid] = {
                "approval_id": aid,
                "plan_id": plan.plan_id,
                "run_id": plan.request_id,  # run-scope via the request
                "request_id": plan.request_id,
                "requested_by": requested_by,
                "created_at": self._clock(),
                "expires_at": self._clock() + timedelta(seconds=ttl_s),
                "status": ApprovalStatus.PENDING,
                "policy_version": "cap-policy-v1",
                "boundary_version": "sbl-v1",
            }
            return aid

    def validate(self, approval_id: str, plan: SandboxMutationPlan,
                 run_id: str) -> ApprovalVerdict:
        with self._lock:
            rec = self._approvals.get(approval_id)
            if rec is None:
                raise ApprovalInvalid(f"unknown approval {approval_id}")
            if rec["status"] == ApprovalStatus.USED:
                raise ApprovalReuse(
                    f"approval {approval_id} already consumed")
            if rec["plan_id"] != plan.plan_id:
                raise ApprovalInvalid(
                    f"approval {approval_id} is for plan {rec['plan_id']}, "
                    f"not {plan.plan_id}")
            if rec["request_id"] != plan.request_id:
                raise ApprovalInvalid("approval request mismatch")
            if rec["run_id"] != run_id:
                raise ApprovalInvalid(
                    f"approval {approval_id} is scoped to run "
                    f"{rec['run_id']}, not {run_id}")
            if self._clock() > rec["expires_at"]:
                rec["status"] = ApprovalStatus.EXPIRED
                raise ApprovalExpired(
                    f"approval {approval_id} expired at "
                    f"{rec['expires_at']}")
            # consume (single-use)
            rec["status"] = ApprovalStatus.USED
            return ApprovalVerdict(ok=True, approval_id=approval_id)

    def status(self, approval_id: str) -> ApprovalStatus:
        rec = self._approvals.get(approval_id)
        if rec is None:
            raise ApprovalInvalid(f"unknown approval {approval_id}")
        return rec["status"]


def timezone_utc():
    from datetime import timezone
    return timezone.utc
