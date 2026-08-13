"""Approval gate (Sprint 1.0.2).

PENDING → APPROVED / REJECTED / EXPIRED. A decided request cannot be
re-decided (raises ApprovalAlreadyDecided); deciding an overdue request
raises ApprovalExpired. The ExecutionEngine pauses at WAITING_APPROVAL
steps until a decision arrives.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

from .events import Clock, utcnow
from .exceptions import ApprovalAlreadyDecided, ApprovalExpired


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    id: str
    run_id: str
    step_id: str
    reason: str = ""
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    # Sprint 1.0.6.3: durable decision metadata (additive — None = undecided).
    decided_by: Optional[str] = None
    decision_source: Optional[str] = None
    decision_reason_code: Optional[str] = None

    @property
    def is_decided(self) -> bool:
        return self.status is not ApprovalStatus.PENDING

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "status": self.status.value,
            "decision_reason": None,
            "decided_by": self.decided_by,
            "decision_source": self.decision_source,
            "decision_reason_code": self.decision_reason_code,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ApprovalRequest":
        from datetime import datetime as _dt

        def _ts(v):
            try:
                return _dt.fromisoformat(v) if v else None
            except ValueError:
                return None

        return cls(
            id=data["id"],
            run_id=data["run_id"],
            step_id=data["step_id"],
            reason=data.get("reason", ""),
            created_at=_ts(data.get("created_at")),
            expires_at=_ts(data.get("expires_at")),
            status=ApprovalStatus(data.get("status", ApprovalStatus.PENDING.value)),
            decided_by=data.get("decided_by"),
            decision_source=data.get("decision_source"),
            decision_reason_code=data.get("decision_reason_code"),
        )


class ApprovalManager:
    def __init__(
        self,
        clock: Optional[Clock] = None,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        self._clock = clock or utcnow
        self._ttl = ttl_seconds
        self._requests: Dict[str, ApprovalRequest] = {}
        self._seq = 0

    def request(
        self,
        run_id: str,
        step_id: str,
        reason: str = "",
        ttl_seconds: Optional[float] = None,
    ) -> ApprovalRequest:
        """Open a PENDING approval request (duplicates are allowed — each
        gate gets its own request)."""
        self._seq += 1
        now = self._clock()
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        request = ApprovalRequest(
            # Sprint 1.0.6.2 fix: globally-unique ids (run prefix) — the
            # approvals table PK is id; a bare "approval-N" repeated per
            # run would silently OVERWRITE the previous run's row.
            id=f"approval-{run_id}-{self._seq}",
            run_id=run_id,
            step_id=step_id,
            reason=reason,
            created_at=now,
            expires_at=(now + timedelta(seconds=ttl)) if ttl else None,
        )
        self._requests[request.id] = request
        return request

    def get(self, approval_id: str) -> ApprovalRequest:
        try:
            return self._requests[approval_id]
        except KeyError:
            raise KeyError(f"unknown approval: {approval_id}") from None

    def list_pending(self) -> List[ApprovalRequest]:
        return [r for r in self._requests.values() if r.status is ApprovalStatus.PENDING]

    def is_overdue(self, request: ApprovalRequest) -> bool:
        return (
            request.status is ApprovalStatus.PENDING
            and request.expires_at is not None
            and self._clock() > request.expires_at
        )

    def approve(self, approval_id: str) -> ApprovalRequest:
        return self._decide(approval_id, ApprovalStatus.APPROVED)

    def reject(self, approval_id: str) -> ApprovalRequest:
        return self._decide(approval_id, ApprovalStatus.REJECTED)

    def expire(self, approval_id: str) -> ApprovalRequest:
        return self._decide(approval_id, ApprovalStatus.EXPIRED)

    def expire_overdue(self) -> List[ApprovalRequest]:
        """Sweep: expire every PENDING request past its expires_at."""
        expired = [r for r in self.list_pending() if self.is_overdue(r)]
        for request in expired:
            request.status = ApprovalStatus.EXPIRED
        return expired

    # ── internals ────────────────────────────────────────────────────

    def _decide(self, approval_id: str, target: ApprovalStatus) -> ApprovalRequest:
        request = self.get(approval_id)
        if request.status is not ApprovalStatus.PENDING:
            raise ApprovalAlreadyDecided(approval_id, request.status.value)
        if self.is_overdue(request):
            request.status = ApprovalStatus.EXPIRED
            raise ApprovalExpired(approval_id)
        request.status = target
        return request
