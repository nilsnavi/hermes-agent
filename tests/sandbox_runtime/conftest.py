"""Shared fixtures for the sandbox_runtime test suite (Sprint 1.3.5)."""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from agent.sandbox_runtime.models import (  # noqa: E402
    ResourceType,
    RiskClass,
    SandboxMutationRequest,
    SandboxOperation,
)
from agent.sandbox_runtime.root import SandboxRoot  # noqa: E402


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def clock():
    """Injectable fixed clock."""
    base = utcnow()

    def _clock() -> datetime:
        return base

    return _clock


@pytest.fixture
def sandbox_root(tmp_path):
    root = SandboxRoot(str(tmp_path / "sandbox"))
    root.ensure()
    return root


def make_request(
    operation: SandboxOperation = SandboxOperation.CREATE_FILE,
    target: str = "data/hello.txt",
    resource_type: ResourceType | None = None,
    arguments: dict | None = None,
    expected_state: str | None = "absent",
    expected_hash: str | None = None,
    approval_id: str | None = "approval-1",
    request_id: str | None = None,
    run_id: str = "run-1",
    step_id: str = "step-1",
    idempotency_key: str = "idem-1",
    risk_class: RiskClass = RiskClass.MEDIUM,
    created_at: datetime | None = None,
    ttl: float = 300.0,
    **kwargs,
) -> SandboxMutationRequest:
    if resource_type is None:
        resource_type = {
            SandboxOperation.CREATE_FILE: ResourceType.FILE,
            SandboxOperation.WRITE_FILE: ResourceType.FILE,
            SandboxOperation.REPLACE_FILE: ResourceType.FILE,
            SandboxOperation.DELETE_FILE: ResourceType.FILE,
            SandboxOperation.RENAME_FILE: ResourceType.FILE,
            SandboxOperation.CREATE_DIRECTORY: ResourceType.DIRECTORY,
            SandboxOperation.DELETE_EMPTY_DIRECTORY: ResourceType.DIRECTORY,
            SandboxOperation.CHMOD: ResourceType.PERMISSION,
            SandboxOperation.WRITE_TEST_CONFIG: ResourceType.CONFIG,
            SandboxOperation.START_SANDBOX_SERVICE: ResourceType.SERVICE,
            SandboxOperation.STOP_SANDBOX_SERVICE: ResourceType.SERVICE,
            SandboxOperation.RESTART_SANDBOX_SERVICE: ResourceType.SERVICE,
            SandboxOperation.RELOAD_SANDBOX_SERVICE: ResourceType.SERVICE,
        }.get(operation, ResourceType.FILE)
    # one request per run in this suite → request_id inherits the run scope
    if request_id is None:
        request_id = run_id
    return SandboxMutationRequest(
        request_id=request_id,
        run_id=run_id,
        step_id=step_id,
        operation=operation,
        resource_type=resource_type,
        target=target,
        arguments=arguments or {},
        expected_state=expected_state,
        expected_hash=expected_hash,
        risk_class=risk_class,
        side_effect=kwargs.pop("side_effect", "MUTATION"),
        policy_version=kwargs.pop("policy_version", "cap-policy-v1"),
        boundary_version=kwargs.pop("boundary_version", "sbl-v1"),
        requested_by=kwargs.pop("requested_by", "test"),
        approval_id=approval_id,
        created_at=created_at or utcnow(),
        ttl=ttl,
        idempotency_key=idempotency_key,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture
def make_req():
    return make_request


@pytest.fixture
def mkfile(sandbox_root):
    def _mk(rel: str, content: str = "hello") -> str:
        path = os.path.join(sandbox_root.root, rel)
        write_text(path, content)
        return path

    return _mk
