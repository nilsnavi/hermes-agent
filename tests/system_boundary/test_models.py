"""Sprint 1.3.3 §5/§10/§11/§39/§50 — SBL data model invariants.

RED phase: these tests define the canonical SBL vocabulary:
resource classes, operation classes, effective action classes, boundary
decisions (PASS/BLOCK/REVALIDATE_REQUIRED), preflight plans, reason
codes and the UNKNOWN-* invariants.
"""

import pytest

from agent.system_boundary import models as m


# ── resource classes (§10) ──────────────────────────────────────────

def test_resource_class_canonical_set():
    assert m.ResourceClass.USER_DATA.value == "USER_DATA"
    assert m.ResourceClass.SYSTEM_CONFIG.value == "SYSTEM_CONFIG"
    assert m.ResourceClass.SECRET_RESOURCE.value == "SECRET_RESOURCE"
    assert m.ResourceClass.UNKNOWN.value == "UNKNOWN"


def test_resource_unknown_invariants():
    # UNKNOWN != SAFE / USER_DATA / NONE
    assert m.ResourceClass.UNKNOWN != m.ResourceClass.USER_DATA
    # there is no SAFE resource class at all
    assert not hasattr(m.ResourceClass, "SAFE")


def test_resource_class_is_restrictive():
    """A SYSTEM_CONFIG resource is never classified as USER_DATA."""
    assert m.ResourceClass.SYSTEM_CONFIG != m.ResourceClass.USER_DATA


# ── operation classes (§11) ─────────────────────────────────────────

def test_operation_class_read_and_mutation():
    assert m.OperationClass.READ.value == "READ"
    assert m.OperationClass.SERVICE_RESTART.value == "SERVICE_RESTART"
    assert m.OperationClass.PROCESS_KILL.value == "PROCESS_KILL"
    assert m.OperationClass.PACKAGE_INSTALL.value == "PACKAGE_INSTALL"


def test_unknown_mutation_never_read():
    """Unknown mutation never classified as READ."""
    assert m.OperationClass.UNKNOWN != m.OperationClass.READ
    assert m.OperationClass.UNKNOWN not in (
        m.OperationClass.READ,
        m.OperationClass.CREATE,
    )


# ── effective action classes (§12/§14) ──────────────────────────────

def test_effective_action_classes():
    assert m.EffectiveActionClass.READ.value == "READ"
    assert m.EffectiveActionClass.INDIRECT_SYSTEM_CONTROL.value == \
        "INDIRECT_SYSTEM_CONTROL"
    assert m.EffectiveActionClass.PROCESS_SELF_CONTROL.value == \
        "PROCESS_SELF_CONTROL"
    assert m.EffectiveActionClass.UNKNOWN.value == "UNKNOWN"


def test_effective_action_unknown_is_mutation_capable():
    """EFFECTIVE_ACTION_UNKNOWN must be treated as mutation-capable."""
    assert m.EffectiveActionClass.UNKNOWN.is_mutation_capable()


# ── boundary decision (§5) ──────────────────────────────────────────

def test_boundary_decision_verdicts():
    d = m.BoundaryDecision(verdict="PASS", reason_code="SBL_OK")
    assert d.verdict == "PASS"
    assert d.allow is True
    b = m.BoundaryDecision(verdict="BLOCK", reason_code="RESOURCE_SYSTEM")
    assert b.allow is False
    r = m.BoundaryDecision(verdict="REVALIDATE_REQUIRED",
                           reason_code="RESOURCE_CHANGED_AFTER_PREFLIGHT")
    assert r.allow is False


def test_boundary_decision_risk_monotonicity_field():
    """risk_after >= risk_before enforced by construction in helpers."""
    d = m.BoundaryDecision(verdict="BLOCK", reason_code="SBL_OK",
                           risk_before="READ_ONLY", risk_after="SYSTEM")
    assert d.risk_before == "READ_ONLY"
    assert d.risk_after == "SYSTEM"


def test_boundary_decision_defaults():
    d = m.BoundaryDecision(verdict="PASS")
    assert d.reason_code == "SBL_OK"
    assert d.resource_class is None
    assert d.operation_class is None
    assert d.blast_radius == "NONE"
    assert d.approval_required is False
    assert d.validation_required is False
    assert d.boundary_version


# ── preflight plan (§21) ────────────────────────────────────────────

def test_preflight_plan_fields():
    p = m.SystemPreflightPlan(
        preflight_id="pf-1",
        execution_id="ex-1",
        request_id="req-1",
        run_id="run-1",
        step_id="step-1",
        tool_name="shell_exec",
        capability="SYSTEM_EXEC",
        operation_class="EXECUTE_SCRIPT",
        effective_action_class="SERVICE_RESTART",
        canonical_targets=["hermes-gateway"],
        arguments_digest="digest",
        effective_risk="SYSTEM",
        risk_floor="SYSTEM",
        blast_radius="SERVICE",
        affected_services=["hermes-gateway"],
        graph_version="g1",
        graph_health="HEALTHY",
        preflight_digest="pd",
    )
    assert p.preflight_digest == "pd"
    assert p.expires_at is None  # TTL optional at construction


# ── reason codes (§50) ──────────────────────────────────────────────

def test_reason_code_canonical_set():
    codes = m.REASON_CODES
    for code in (
        "SBL_OK",
        "RESOURCE_UNKNOWN",
        "RESOURCE_SYSTEM",
        "RESOURCE_CHANGED_AFTER_PREFLIGHT",
        "PATH_UNRESOLVED",
        "PATH_ESCAPE_DETECTED",
        "SYMLINK_ESCAPE",
        "OPERATION_UNKNOWN",
        "EFFECTIVE_ACTION_UNKNOWN",
        "INDIRECT_SYSTEM_CONTROL",
        "PROCESS_SELF_CONTROL_FORBIDDEN",
        "NETWORK_TARGET_UNKNOWN",
        "SECRET_RESOURCE_DETECTED",
        "BOUNDARY_BYPASS_DETECTED",
        "DEPENDENCY_UNKNOWN",
        "BLAST_RADIUS_UNKNOWN",
        "BLAST_RADIUS_HIGH",
        "SERVICE_GRAPH_STALE",
        "SERVICE_GRAPH_PARTIAL",
        "SERVICE_GRAPH_UNAVAILABLE",
        "SERVICE_GRAPH_CORRUPT",
        "PREFLIGHT_REQUIRED",
        "PREFLIGHT_EXPIRED",
        "PREFLIGHT_MISMATCH",
        "VALIDATION_REQUIRED",
        "VALIDATION_UNAVAILABLE",
        "POSTCHECK_REQUIRED",
        "SBL_INTERNAL_ERROR",
    ):
        assert code in codes, f"missing reason code {code}"


# ── blast radius (§39) ──────────────────────────────────────────────

def test_blast_radius_unknown_neq_none():
    assert m.BlastRadius.UNKNOWN != m.BlastRadius.NONE


def test_graph_health_unknown_not_empty():
    """Incomplete dependency set != empty (§37)."""
    assert m.GraphHealth.PARTIAL != m.GraphHealth.HEALTHY
    assert m.GraphHealth.UNAVAILABLE != m.GraphHealth.HEALTHY
