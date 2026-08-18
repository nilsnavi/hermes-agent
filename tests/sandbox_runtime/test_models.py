"""Sandbox mutation models — strict request/plan validation (Sprint 1.3.5 §6-§7)."""

from __future__ import annotations

import pytest

from tests.sandbox_runtime.conftest import make_request, utcnow
from agent.sandbox_runtime.exceptions import SandboxModelError
from agent.sandbox_runtime.models import (
    ResourceType,
    RiskClass,
    SandboxMutationPlan,
    SandboxMutationRequest,
    SandboxOperation,
    TransactionState,
    plan_changed_after_approval,
)


def test_request_requires_idempotency_key(make_req):
    req = make_request(idempotency_key="idem-1")
    assert req.idempotency_key == "idem-1"


def test_request_unknown_field_rejected(make_req):
    with pytest.raises(SandboxModelError):
        SandboxMutationRequest.from_dict(
            make_request().to_dict() | {"totally_unknown": 1})


def test_request_operation_resource_type_must_match(make_req):
    req = make_request(
        operation=SandboxOperation.CREATE_FILE,
        resource_type=ResourceType.SERVICE,  # mismatched
    )
    assert req.validate() is False


def test_request_ttl_positive(make_req):
    req = make_request(ttl=-5.0)
    assert req.validate() is False


def test_request_frozen(make_req):
    req = make_request()
    with pytest.raises(Exception):
        req.target = "/etc/passwd"  # type: ignore[misc]


def test_operation_enum_surface():
    ops = {o.value for o in SandboxOperation}
    assert {
        "CREATE_FILE", "WRITE_FILE", "REPLACE_FILE", "DELETE_FILE",
        "RENAME_FILE", "CREATE_DIRECTORY", "DELETE_EMPTY_DIRECTORY",
        "CHMOD", "WRITE_TEST_CONFIG", "START_SANDBOX_SERVICE",
        "STOP_SANDBOX_SERVICE", "RESTART_SANDBOX_SERVICE",
        "RELOAD_SANDBOX_SERVICE",
    } <= ops


def test_transaction_state_machine_enum_surface():
    states = {s.value for s in TransactionState}
    assert "COMMITTED" in states
    assert "ROLLED_BACK" in states
    assert "MANUAL_REVIEW_REQUIRED" in states
    assert "UNKNOWN_OUTCOME" in states


def test_plan_frozen_after_approval(make_req):
    req = make_request()
    plan = SandboxMutationPlan(
        plan_id="plan-1",
        request_id=req.request_id,
        resolved_target="/sandbox/data/hello.txt",
        operation=req.operation,
        resource_type=req.resource_type,
        before_state="absent",
        expected_after_state="present",
        risk=req.risk_class,
        approval_required=True,
        backup_required=True,
        verification_strategy="hash",
        rollback_strategy="snapshot",
        health_strategy="sandbox",
        preflight_fingerprint="fp-1",
        created_at=utcnow(),
        expires_at=None,
    )
    plan.lock_after_approval()
    assert plan.approved
    # any mutation attempt after approval must be refused
    with pytest.raises(SandboxModelError):
        plan_changed_after_approval(plan, "before_state", "present")


def test_plan_immutability_guard(make_req):
    req = make_request()
    plan = SandboxMutationPlan(
        plan_id="plan-2",
        request_id=req.request_id,
        resolved_target="/sandbox/x",
        operation=req.operation,
        resource_type=req.resource_type,
        before_state="absent",
        expected_after_state="present",
        risk=req.risk_class,
        approval_required=True,
        backup_required=True,
        verification_strategy="hash",
        rollback_strategy="snapshot",
        health_strategy="sandbox",
        preflight_fingerprint="fp-2",
        created_at=utcnow(),
        expires_at=None,
    )
    # not approved yet — no lock, plain object
    assert plan.approved is False


def test_request_to_dict_roundtrip(make_req):
    req = make_request()
    assert SandboxMutationRequest.from_dict(req.to_dict()) == req


def test_risk_class_values():
    assert {r.value for r in RiskClass} == {"LOW", "MEDIUM", "HIGH"}
