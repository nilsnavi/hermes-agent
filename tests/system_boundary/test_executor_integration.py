"""Sprint 1.3.3 §3/§26/§61/§62/§63 — EXECUTOR INTEGRATION (P0).

VerifiedToolExecutor must run the full boundary pipeline:

    preflight → authorize → verify_before_execute → adapter
               → verify_after_execute

and the P0 self-restart / TOCTOU / preflight-mismatch scenarios must
end with adapter calls = 0.
"""

import os
import tempfile

import pytest

from agent.verified_tool_executor.executor import VerifiedToolExecutor
from agent.verified_tool_executor.models import ExecutionStatus
from agent.verified_tool_executor.receipts import MemoryReceiptStore
from agent.verified_tool_executor.registry import VerifiedToolRegistry
from tests.system_boundary.conftest import (
    DummyAdapter,
    make_command_request,
    make_request,
)


def _make_executor(boundary, adapter=None, registry=None):
    reg = registry or VerifiedToolRegistry()
    adapter = adapter or DummyAdapter()
    reg.bind("runtime_status", adapter,
             argument_schema={"fields": {
                 "command": {"type": "str", "required": False},
                 "path": {"type": "str", "required": False},
                 "target": {"type": "str", "required": False},
             }})
    return VerifiedToolExecutor(
        reg, receipts=MemoryReceiptStore(), boundary=boundary), adapter


def _sbl():
    from agent.system_boundary.boundary import SystemBoundaryLayer
    return SystemBoundaryLayer(mode="enforce")


# ── pipeline shape ──────────────────────────────────────────────────

def test_executor_consults_preflight_authorize_verify():
    from agent.system_boundary.boundary import SystemBoundaryLayer

    calls = []
    class TrackingBoundary(SystemBoundaryLayer):
        def preflight(self, request, descriptor):
            calls.append("preflight")
            return super().preflight(request, descriptor)

        def authorize(self, request, descriptor, preflight):
            calls.append("authorize")
            return super().authorize(request, descriptor, preflight)

        def verify_before_execute(self, request, descriptor, preflight):
            calls.append("verify_before_execute")
            return super().verify_before_execute(request, descriptor,
                                                 preflight)

        def verify_after_execute(self, request, descriptor, result,
                                 preflight):
            calls.append("verify_after_execute")
            return super().verify_after_execute(request, descriptor,
                                                result, preflight)

    ex, adapter = _make_executor(TrackingBoundary(mode="enforce"))
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.SUCCEEDED
    assert calls == ["preflight", "authorize", "verify_before_execute",
                     "verify_after_execute"]
    assert adapter.calls == 1


# ── P0: self-restart via executor ───────────────────────────────────

def test_executor_blocks_gateway_restart_command():
    """A request whose payload hides systemctl restart hermes-gateway
    is BLOCKED with adapter calls = 0."""
    ex, adapter = _make_executor(_sbl())
    req = make_command_request(
        command="systemctl --user restart hermes-gateway",
        idempotency_key="idem-sr")
    res = ex.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert adapter.calls == 0


def test_executor_blocks_indirect_restart_via_bash_c():
    ex, adapter = _make_executor(_sbl())
    req = make_command_request(
        command="bash -c \"systemctl --user restart hermes-gateway\"",
        idempotency_key="idem-bash")
    res = ex.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert adapter.calls == 0


def test_executor_read_only_command_passes():
    ex, adapter = _make_executor(_sbl())
    req = make_command_request(
        command="systemctl status nginx",
        idempotency_key="idem-ok")
    res = ex.execute(req)
    assert res.status is ExecutionStatus.SUCCEEDED
    assert adapter.calls == 1


# ── P0: TOCTOU through executor ─────────────────────────────────────

def test_executor_toctou_blocks_adapter(tmp_path):
    from agent.system_boundary.boundary import SystemBoundaryLayer

    target = tmp_path / "data.txt"
    target.write_text("v1")

    class ToctouBoundary(SystemBoundaryLayer):
        def __init__(self):
            super().__init__(mode="enforce")
            self._preflighted = False

        def preflight(self, request, descriptor):
            plan = super().preflight(request, descriptor)
            self._preflighted = True
            return plan

        def verify_before_execute(self, request, descriptor, preflight):
            # swap target for a symlink between preflight and verify
            if self._preflighted and os.path.exists(str(target)) \
                    and not os.path.islink(str(target)):
                os.unlink(target)
                os.symlink("/etc/passwd", target)
            return super().verify_before_execute(request, descriptor,
                                                 preflight)

    ex, adapter = _make_executor(ToctouBoundary())
    req = make_request(
        arguments={"path": str(target)},
        idempotency_key="idem-toctou",
        expected_side_effect="SYSTEM_CHANGE",
        expected_risk_class="SYSTEM",
        capability="SYSTEM_EXEC",
        tool_name="runtime_status",  # registry constraint
    )
    res = ex.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert adapter.calls == 0


# ── P0: preflight mismatch through executor ─────────────────────────

def test_executor_rejects_preflight_reuse_for_different_action():
    """A preflight for 'restart nginx' must not allow 'restart ssh'."""
    from agent.system_boundary.boundary import SystemBoundaryLayer

    class ReplayBoundary(SystemBoundaryLayer):
        def __init__(self):
            super().__init__(mode="enforce")
            self._cached_plan = None

        def preflight(self, request, descriptor):
            self._cached_plan = super().preflight(request, descriptor)
            return self._cached_plan

        def verify_before_execute(self, request, descriptor, preflight):
            # swap the operation between preflight and verify
            from agent.system_boundary import effective_action as ea
            r = ea.classify_command("systemctl restart ssh")
            return super().verify_before_execute(
                request, descriptor, preflight,
                operation_override=r.operation_class,
                target_override=r.targets)

    ex, adapter = _make_executor(ReplayBoundary())
    req = make_command_request(
        command="systemctl restart nginx",
        idempotency_key="idem-replay")
    res = ex.execute(req)
    assert res.status is ExecutionStatus.REJECTED
    assert adapter.calls == 0


# ── bypass: executor cannot be bypassed in production V2 ────────────

def test_direct_adapter_execution_without_boundary_blocked():
    """Calling the adapter directly (outside executor) with the SBL
    guard in place must raise BOUNDARY_BYPASS_DETECTED."""
    from agent.system_boundary.boundary import SystemBoundaryLayer
    from agent.system_boundary.guard import execute_requires_boundary

    sbl = SystemBoundaryLayer(mode="enforce")
    with pytest.raises(Exception) as ei:
        execute_requires_boundary()
    assert "BOUNDARY_BYPASS" in str(ei.value)


# ── Noop boundary backward compatibility ────────────────────────────

def test_noop_boundary_still_works():
    """The executor contract must remain backward compatible with the
    Sprint 1.3.2 NoopSystemBoundary."""
    from agent.verified_tool_executor.boundary import NoopSystemBoundary
    ex, adapter = _make_executor(NoopSystemBoundary())
    res = ex.execute(make_request())
    assert res.status is ExecutionStatus.SUCCEEDED
    assert adapter.calls == 1
