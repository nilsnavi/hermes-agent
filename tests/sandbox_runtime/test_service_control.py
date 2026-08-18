"""Sandbox test-service control — start/stop/restart/reload, identity guard (Sprint 1.3.5 §16)."""

from __future__ import annotations

import os
import time

import pytest

from tests.sandbox_runtime.conftest import utcnow
from agent.sandbox_runtime.exceptions import SandboxServiceError
from agent.sandbox_runtime.service import SandboxTestService


@pytest.fixture
def service(sandbox_root):
    svc = SandboxTestService(sandbox_root, name="hermes-sandbox-test")
    return svc


def test_service_start_creates_pid(sandbox_root, service):
    service.start()
    try:
        assert service.pid() > 0
        assert service.is_running()
    finally:
        service.stop()


def test_service_stop_terminates(sandbox_root, service):
    service.start()
    pid = service.pid()
    service.stop()
    assert not service.is_running()
    with pytest.raises(SandboxServiceError):
        service.pid()
    # process must actually be gone
    assert not os.path.exists(f"/proc/{pid}")


def test_service_restart_changes_pid(sandbox_root, service):
    service.start()
    try:
        pid1 = service.pid()
        service.restart()
        pid2 = service.pid()
        assert pid2 != pid1
    finally:
        service.stop()


def test_service_reload_keeps_pid(sandbox_root, service):
    service.start()
    try:
        pid1 = service.pid()
        service.reload()
        assert service.pid() == pid1
    finally:
        service.stop()


def test_service_health_probe(sandbox_root, service):
    service.start()
    try:
        assert service.health_probe() is True
    finally:
        service.stop()


def test_service_stop_when_not_running(sandbox_root, service):
    with pytest.raises(SandboxServiceError):
        service.stop()


def test_production_service_blocked(sandbox_root, make_req):
    # hermes-gateway.service must never be controllable via sandbox service
    from agent.sandbox_runtime.service import assert_sandbox_service_identity
    with pytest.raises(SandboxServiceError):
        assert_sandbox_service_identity("hermes-gateway.service")


def test_service_writes_marker_inside_sandbox(sandbox_root, service):
    service.start()
    try:
        marker = os.path.join(sandbox_root.root, ".service", "state.json")
        assert os.path.exists(marker)
    finally:
        service.stop()


def test_service_restart_after_crash(sandbox_root, service):
    service.start()
    pid = service.pid()
    os.kill(pid, 9)  # simulate crash
    time.sleep(0.1)
    service.restart()  # must recover
    assert service.is_running()
    service.stop()
