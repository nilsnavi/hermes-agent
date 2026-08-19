"""Sprint 1.3.12 — approval foundation (shadow-only, never grants execution)."""
from __future__ import annotations

from agent.service_restart_foundation.approval import (
    ApprovalVerdict,
    approval_grants_execution,
    evaluate_approval,
)


class TestApproval:
    def test_shadow_approval_when_all_ok(self):
        a = evaluate_approval(
            service_id="s", plan_hash="h", profile_version=1,
            old_identity="old", graph_digest="g", risk="HIGH",
            blast_radius="SERVICE", health_ok=True, rollback_ok=True,
        )
        assert a.verdict == ApprovalVerdict.APPROVED_SHADOW

    def test_denied_when_health_fail(self):
        a = evaluate_approval(
            service_id="s", plan_hash="h", profile_version=1,
            old_identity="old", graph_digest="g", risk="HIGH",
            blast_radius="SERVICE", health_ok=False, rollback_ok=True,
        )
        assert a.verdict == ApprovalVerdict.DENIED

    def test_approval_never_grants_execution(self):
        # even a shadow-approved plan cannot execute in 1.3.12
        a = evaluate_approval(
            service_id="s", plan_hash="h", profile_version=1,
            old_identity="old", graph_digest="g", risk="HIGH",
            blast_radius="SERVICE", health_ok=True, rollback_ok=True,
        )
        out = approval_grants_execution(a)
        assert "SERVICE_RESTART_DISABLED" in out

    def test_bound_fields_present(self):
        a = evaluate_approval(
            service_id="s", plan_hash="h", profile_version=2,
            old_identity="old", graph_digest="g", risk="HIGH",
            blast_radius="SERVICE", health_ok=True, rollback_ok=True,
        )
        assert "s" in a.bound_fields and "h" in a.bound_fields
        assert "defused_by_plan_hash" not in a.bound_fields