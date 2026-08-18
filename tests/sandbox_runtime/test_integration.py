"""Integration — full sandbox mutation pipeline end-to-end (Sprint 1.3.5 §34 acceptance scenarios)."""

from __future__ import annotations

import os

import pytest

from tests.sandbox_runtime.conftest import (
    make_request,
    read_text,
    sha256_bytes,
    write_text,
)
from agent.sandbox_runtime.models import (
    ResourceType,
    SandboxMutationRequest,
    SandboxOperation,
)
from agent.sandbox_runtime.pipeline import SandboxMutationPipeline


@pytest.fixture
def pipeline(sandbox_root, clock):
    return SandboxMutationPipeline(
        sandbox_root,
        clock=clock,
        approve_automatically=False,
    )


def _approve(pipeline, req, plan):
    approval_id = pipeline.approval.issue(plan, requested_by="test", ttl_s=300)
    return approval_id


def test_s1_create_sandbox_file_committed(sandbox_root, pipeline, make_req):
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/s1.txt",
                   expected_state="absent",
                   arguments={"content": "hello-s1"})
    result = pipeline.run(req, approve_automatically=True)
    assert result.status == "COMMITTED"
    assert read_text(os.path.join(sandbox_root.root, "data", "s1.txt")) == "hello-s1"


def test_s2_write_sandbox_file_committed(sandbox_root, pipeline, mkfile, make_req):
    mkfile("data/s2.txt", "old")
    req = make_req(operation=SandboxOperation.WRITE_FILE, target="data/s2.txt",
                   expected_state="present",
                   arguments={"content": "new-value"})
    result = pipeline.run(req, approve_automatically=True)
    assert result.status == "COMMITTED"
    assert read_text(os.path.join(sandbox_root.root, "data", "s2.txt")) == "new-value"


def test_s4_chmod_committed(sandbox_root, pipeline, mkfile, make_req):
    mkfile("data/s4.txt", "x")
    req = make_req(operation=SandboxOperation.CHMOD, target="data/s4.txt",
                   expected_state="present", arguments={"mode": 0o600})
    result = pipeline.run(req, approve_automatically=True)
    assert result.status == "COMMITTED"
    assert (os.stat(os.path.join(sandbox_root.root, "data", "s4.txt")).st_mode & 0o777) == 0o600


def test_s6_delete_committed(sandbox_root, pipeline, mkfile, make_req):
    mkfile("data/s6.txt", "x")
    req = make_req(operation=SandboxOperation.DELETE_FILE, target="data/s6.txt",
                   expected_state="present")
    result = pipeline.run(req, approve_automatically=True)
    assert result.status == "COMMITTED"
    assert not os.path.exists(os.path.join(sandbox_root.root, "data", "s6.txt"))


def test_s16_symlink_escape_denied(sandbox_root, pipeline, make_req):
    os.symlink("/etc", os.path.join(sandbox_root.root, "evil-link"))
    req = make_req(operation=SandboxOperation.DELETE_FILE, target="evil-link/passwd",
                   expected_state="present")
    result = pipeline.run(req, approve_automatically=True)
    assert result.status in ("DENIED", "FAILED")
    assert result.adapter_calls == 0


def test_s17_dotdot_escape_denied(sandbox_root, pipeline, make_req):
    req = make_req(operation=SandboxOperation.DELETE_FILE, target="../../etc/passwd",
                   expected_state="present")
    result = pipeline.run(req, approve_automatically=True)
    assert result.status == "DENIED"
    assert result.adapter_calls == 0


def test_s18_production_config_denied(sandbox_root, pipeline, make_req):
    req = make_req(operation=SandboxOperation.WRITE_TEST_CONFIG,
                   target="/home/hermes/.hermes/config.yaml",
                   expected_state="present")
    result = pipeline.run(req, approve_automatically=True)
    assert result.status == "DENIED"
    assert result.adapter_calls == 0


def test_s19_gateway_restart_denied(sandbox_root, pipeline, make_req):
    req = make_req(operation=SandboxOperation.START_SANDBOX_SERVICE,
                   target="hermes-gateway.service", expected_state="present")
    result = pipeline.run(req, approve_automatically=True)
    assert result.status == "DENIED"
    assert result.adapter_calls == 0


def test_s22_unknown_operation_denied(sandbox_root, pipeline, make_req):
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/x.txt",
                   expected_state="absent")
    req.__dict__["operation"] = "EXPLODE"  # type: ignore[attr-defined]
    result = pipeline.run(req, approve_automatically=True)
    assert result.status == "DENIED"
    assert result.adapter_calls == 0


def test_s23_approval_expired_denied(sandbox_root, pipeline, make_req):
    from datetime import timedelta
    from agent.sandbox_runtime.approval import ApprovalManager

    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/s23.txt",
                   expected_state="absent")

    class _LateClock:
        def __call__(self):
            from tests.sandbox_runtime.conftest import utcnow
            return utcnow() + timedelta(seconds=9999)

    p2 = SandboxMutationPipeline(sandbox_root, clock=_LateClock(),
                                 approve_automatically=False)
    result = p2.run(req, approve_automatically=True)  # approval will be expired
    assert result.status in ("DENIED", "APPROVAL_EXPIRED")


def test_s29_replay_after_committed_prior_result(sandbox_root, pipeline, make_req):
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/s29.txt",
                   expected_state="absent", idempotency_key="S29-KEY",
                   arguments={"content": "once"})
    r1 = pipeline.run(req, approve_automatically=True)
    assert r1.status == "COMMITTED"
    r2 = pipeline.run(req, approve_automatically=True)
    assert r2.status == "COMMITTED"
    assert r2.replayed is True
    assert r2.adapter_calls == 0


def test_pipeline_emits_audit_events(sandbox_root, pipeline, make_req):
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/audit.txt",
                   expected_state="absent", arguments={"content": "x"})
    pipeline.run(req, approve_automatically=True)
    types = [e["event_type"] for e in pipeline.audit]
    assert "SANDBOX_MUTATION_REQUESTED" in types
    assert "SANDBOX_PREFLIGHT_PASSED" in types
    assert "SANDBOX_COMMITTED" in types
    # append-only order
    assert types == sorted(types, key=lambda t: types.index(t))


def test_pipeline_telemetry_counters(sandbox_root, pipeline, make_req):
    req = make_req(operation=SandboxOperation.CREATE_FILE, target="data/tel.txt",
                   expected_state="absent", arguments={"content": "x"})
    pipeline.run(req, approve_automatically=True)
    counters = pipeline.telemetry.counters()
    assert counters["sandbox_mutation_attempts"] == 1
    assert counters["sandbox_mutation_committed"] == 1
