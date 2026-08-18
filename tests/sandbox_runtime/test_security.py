"""Security — secrets scan, deny matrix, gateway self-control, indirect control (Sprint 1.3.5 §28/§49)."""

from __future__ import annotations

import os
import re

import pytest

from tests.sandbox_runtime.conftest import make_request, write_text
from agent.sandbox_runtime.exceptions import (
    GatewaySelfControlBlocked,
    IndirectControlBlocked,
    SandboxPathEscape,
)
from agent.sandbox_runtime.models import SandboxOperation
from agent.sandbox_runtime.security import (
    GatewayGuard,
    scan_for_secrets,
)


def test_secret_scan_clean_files(tmp_path):
    f = os.path.join(str(tmp_path), "clean.txt")
    write_text(f, "hello world, no secrets here")
    findings = scan_for_secrets([f])
    assert findings == []


def test_secret_scan_finds_token(tmp_path):
    f = os.path.join(str(tmp_path), "bad.txt")
    write_text(f, "Authorization: Bearer sk-abc123secret")
    findings = scan_for_secrets([f])
    assert findings
    assert any("Authorization" in fn or "Bearer" in fn for fn in findings)


def test_secret_scan_finds_api_key(tmp_path):
    f = os.path.join(str(tmp_path), "key.txt")
    write_text(f, "api_key = 'AIzaSyD-very-secret-key-1234567890'")
    findings = scan_for_secrets([f])
    assert any("api_key" in fn or "AIza" in fn for fn in findings)


def test_secret_scan_finds_private_key(tmp_path):
    f = os.path.join(str(tmp_path), "id_rsa")
    write_text(f, "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----")
    findings = scan_for_secrets([f])
    assert findings


def test_gateway_self_restart_blocked(sandbox_root, make_req):
    guard = GatewayGuard()
    req = make_req(operation=SandboxOperation.WRITE_TEST_CONFIG,
                   target="config/test.conf",
                   arguments={"content": "systemctl --user restart hermes-gateway"})
    with pytest.raises(GatewaySelfControlBlocked):
        guard.check(req)


def test_indirect_gateway_restart_via_script_blocked(sandbox_root, make_req):
    guard = GatewayGuard()
    req = make_req(operation=SandboxOperation.CREATE_FILE,
                   target="scripts/restart.sh",
                   arguments={"content": "#!/bin/bash\nsystemctl --user restart hermes-gateway\n"})
    with pytest.raises(IndirectControlBlocked):
        guard.check(req)


def test_bash_c_systemctl_blocked(sandbox_root, make_req):
    guard = GatewayGuard()
    req = make_req(operation=SandboxOperation.WRITE_TEST_CONFIG,
                   target="config/x.conf",
                   arguments={"content": 'bash -c "systemctl restart hermes-gateway"'})
    with pytest.raises(IndirectControlBlocked):
        guard.check(req)


def test_normal_content_not_blocked(sandbox_root, make_req):
    guard = GatewayGuard()
    req = make_req(operation=SandboxOperation.WRITE_TEST_CONFIG,
                   target="config/app.conf",
                   arguments={"content": "port=8080\nworkers=2"})
    guard.check(req)  # must not raise


def test_gateway_service_identity_always_denied(sandbox_root, make_req):
    guard = GatewayGuard()
    for op in (SandboxOperation.START_SANDBOX_SERVICE,
               SandboxOperation.RESTART_SANDBOX_SERVICE):
        req = make_req(operation=op, target="hermes-gateway.service",
                       resource_type="SERVICE")
        with pytest.raises(GatewaySelfControlBlocked):
            guard.check(req)


def test_production_paths_in_arguments_blocked(sandbox_root, make_req):
    guard = GatewayGuard()
    req = make_req(operation=SandboxOperation.WRITE_TEST_CONFIG,
                   target="config/x.conf",
                   arguments={"path": "/home/hermes/.hermes/config.yaml"})
    with pytest.raises(SandboxPathEscape):
        guard.check(req)


def test_secret_patterns_are_known():
    patterns = scan_for_secrets.__globals__.get("SECRET_PATTERNS")
    assert patterns
    joined = " ".join(patterns)
    for marker in ("api", "password", "Bearer", "PRIVATE KEY", "token",
                   "Authorization", "secret", "cookie"):
        assert marker.lower() in joined.lower(), marker
