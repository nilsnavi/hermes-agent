"""Sprint 1.3.15 — approval model.

The multi-service approval confirms global intent but NEVER replaces child
approvals: every child still requires its own validated binding.  A binding is
frozen to the full transaction/plan/graph/risk/blast context with a TTL; any
drift invalidates it.
"""
from __future__ import annotations

import time

from ._durable import CoordinationStore


class ApprovalBinder:
    """Binds and validates global + per-child approval contracts."""

    def __init__(self, store: CoordinationStore, *, clock=lambda: time.time()) -> None:
        self.store = store
        self.clock = clock

    def bind_global(self, approval_id: str, binding: dict, ttl: float = 60.0) -> bool:
        binding = dict(binding)
        binding["_issued_at"] = self.clock()
        binding["_expires_at"] = self.clock() + ttl
        return self.store.bind_approval(approval_id, binding)

    def validate_binding(self, approval_id: str, expected: dict, now: float | None = None) -> str:
        """Returns APPROVED or a precise drift reason."""
        store_rec = self.store._approvals.read().get(approval_id)
        if store_rec is None:
            return "APPROVAL_UNKNOWN"
        if store_rec.get("consumed"):
            return "APPROVAL_USED"
        binding = store_rec.get("binding") or {}
        now = self.clock() if now is None else now
        expires = binding.get("_expires_at")
        if expires is not None and now > expires:
            return "APPROVAL_EXPIRED"
        # immutable identity fields must match exactly
        frozen = {
            k: binding.get(k) for k in
            ("transaction", "service_set", "service_versions", "operation_set",
             "plan_hash", "graph_digest", "risk", "blast", "ttl")
        }
        frozen_expected = {k: expected.get(k) for k in frozen}
        if frozen != frozen_expected:
            return "APPROVAL_BINDING_MISMATCH"
        return "APPROVED"

    def consume(self, approval_id: str) -> bool:
        return self.store.consume_approval(approval_id)


__all__ = ["ApprovalBinder"]