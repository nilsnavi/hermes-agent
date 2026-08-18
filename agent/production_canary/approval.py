"""Sprint 1.3.7 §11 — explicit single-use operator approval bound to the exact plan.

An approval is: version-bound, short TTL, single-use, and cryptographically
bound to {transaction_id, plan_hash, target fingerprint, before hash,
expected-after hash, operation, risk, baseline SHA}. Changing the plan after
approval invalidates it.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Optional

from .core import APPROVAL_TTL_SECONDS, APPROVAL_VERSION


@dataclass(frozen=True)
class Approval:
    approval_id: str
    transaction_id: str
    plan_hash: str
    target_fingerprint: str
    before_hash: str
    expected_after_hash: str
    operation: str
    risk: str
    baseline_sha: str
    issued_at: float
    ttl: float
    version: int
    used: bool = False

    def expired(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return now - self.issued_at > self.ttl

    def plan_matches(self, plan_hash: str) -> bool:
        return self.plan_hash == plan_hash

    def covers(self, *, target_fingerprint: str, before_hash: str,
               expected_after_hash: str, operation: str, risk: str,
               baseline_sha: str) -> bool:
        return (self.target_fingerprint == target_fingerprint
                and self.before_hash == before_hash
                and self.expected_after_hash == expected_after_hash
                and self.operation == operation
                and self.risk == risk
                and self.baseline_sha == baseline_sha)


def fingerprint_target(target: str) -> str:
    return hashlib.sha256(target.encode("utf-8")).hexdigest()


def plan_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


class ApprovalRegistry:
    """Single-use, in-memory approval store (operator grants one per plan)."""

    def __init__(self) -> None:
        self._store: dict[str, Approval] = {}

    def grant(self, *, transaction_id: str, plan_hash: str, target_fingerprint: str,
              before_hash: str, expected_after_hash: str, operation: str,
              risk: str, baseline_sha: str, ttl: float = APPROVAL_TTL_SECONDS,
              issued_at: float | None = None,
              version: int = APPROVAL_VERSION) -> Approval:
        approval = Approval(
            approval_id=f"appr-{transaction_id}-{int(time.time()*1000)}",
            transaction_id=transaction_id, plan_hash=plan_hash,
            target_fingerprint=target_fingerprint, before_hash=before_hash,
            expected_after_hash=expected_after_hash, operation=operation,
            risk=risk, baseline_sha=baseline_sha,
            issued_at=time.time() if issued_at is None else issued_at,
            ttl=ttl, version=version,
        )
        self._store[approval.approval_id] = approval
        return approval

    def validate_and_consume(self, approval_id: str, *, plan_hash: str,
                             target_fingerprint: str, before_hash: str,
                             expected_after_hash: str, operation: str,
                             risk: str, baseline_sha: str,
                             now: float | None = None) -> bool:
        """Consume a single-use approval only if fully valid and plan-identical."""
        a = self._store.get(approval_id)
        if a is None:
            return False
        if a.used:
            return False
        if a.version != APPROVAL_VERSION:
            return False
        if a.expired(now):
            return False
        if not a.plan_matches(plan_hash):
            return False
        if not a.covers(target_fingerprint=target_fingerprint,
                        before_hash=before_hash,
                        expected_after_hash=expected_after_hash,
                        operation=operation, risk=risk, baseline_sha=baseline_sha):
            return False
        # single use: consume immediately after validation
        a = Approval(**{**a.__dict__, "used": True})
        self._store[approval_id] = a
        return True

    def revoke(self, approval_id: str) -> None:
        self._store.pop(approval_id, None)
