"""Sprint 1.3.3 §46/§6/§49/§60 — BYPASS, RISK MONOTONICITY, FAIL CLOSED.

With SBL enabled, a VerifiedToolAdapter cannot execute in the
production V2 path while bypassing SystemBoundary. Exception → BLOCK,
never PASS. risk_after >= risk_before always.
"""

import pytest

from agent.system_boundary import models as m


# ── §46 boundary bypass ─────────────────────────────────────────────

def test_bypass_guard_blocks_direct_adapter_call():
    """A direct adapter invocation outside the executor/SBL pipeline is
    detected as BOUNDARY_BYPASS_DETECTED."""
    from agent.system_boundary.boundary import SystemBoundaryLayer
    from agent.system_boundary.guard import guarded_execute

    calls = []
    def adapter(context, arguments):
        calls.append(1)
        return {"ok": True}

    with pytest.raises(Exception) as ei:
        guarded_execute(adapter, {}, {})
    assert "BOUNDARY_BYPASS" in str(ei.value)


def test_bypass_guard_detected_without_sbl_token():
    from agent.system_boundary.guard import execute_requires_boundary

    with pytest.raises(Exception) as ei:
        execute_requires_boundary()
    assert "BOUNDARY_BYPASS" in str(ei.value)


def test_bypass_through_fake_registry_impossible():
    """A fake registry cannot sneak an adapter past the boundary when
    the executor wraps adapter calls with the SBL guard."""
    from agent.system_boundary.boundary import SystemBoundaryLayer
    from agent.system_boundary.guard import SBLGuardToken

    sbl = SystemBoundaryLayer(mode="enforce")
    token = SBLGuardToken(sbl=sbl, execution_id="ex-1")
    called = []
    def adapter(context, arguments):
        called.append(1)
        return {"ok": True}
    out = sbl.call_adapter(adapter, {}, {}, token=token)
    assert out == {"ok": True}
    assert len(called) == 1


def test_bypass_guard_requires_valid_token():
    from agent.system_boundary.boundary import SystemBoundaryLayer
    from agent.system_boundary.guard import SBLGuardToken

    sbl = SystemBoundaryLayer(mode="enforce")
    # forged token from another SBL instance must not pass
    other = SystemBoundaryLayer(mode="enforce")
    forged = SBLGuardToken(sbl=other, execution_id="forged")
    with pytest.raises(Exception) as ei:
        sbl.call_adapter(lambda c, a: {"ok": True}, {}, {},
                         token=forged)
    assert "BOUNDARY_BYPASS" in str(ei.value)


# ── §6 risk monotonicity ────────────────────────────────────────────

def test_risk_floor_never_decreases():
    from agent.system_boundary.risk import apply_risk_floor
    assert apply_risk_floor("READ_ONLY", "SYSTEM") == "SYSTEM"
    assert apply_risk_floor("SYSTEM", "READ_ONLY") == "SYSTEM"
    assert apply_risk_floor("READ_ONLY", "READ_ONLY") == "READ_ONLY"


def test_risk_monotonicity_invariant():
    """max(intent, capability, tool, context, sbl_floor) — SBL floor
    can only raise."""
    from agent.system_boundary.risk import effective_risk
    r = effective_risk(
        intent_risk="READ_ONLY",
        capability_risk="READ_ONLY",
        tool_risk="READ_ONLY",
        context_risk="READ_ONLY",
        sbl_risk_floor="SYSTEM",
    )
    assert r == "SYSTEM"
    r2 = effective_risk(
        intent_risk="SYSTEM",
        capability_risk="READ_ONLY",
        tool_risk="READ_ONLY",
        context_risk="READ_ONLY",
        sbl_risk_floor="READ_ONLY",
    )
    assert r2 == "SYSTEM"


def test_risk_level_ordering():
    from agent.system_boundary.risk import RISK_ORDER
    assert RISK_ORDER.index("READ_ONLY") < RISK_ORDER.index("SYSTEM")
    assert RISK_ORDER.index("SYSTEM") < RISK_ORDER.index("CRITICAL")


# ── §49 fail closed ─────────────────────────────────────────────────

def test_exception_in_classifier_blocks(tmp_path):
    """A broken path resolver must yield SBL_INTERNAL_ERROR → BLOCK,
    never a silent PASS."""
    from agent.system_boundary.boundary import SystemBoundaryLayer
    from agent.system_boundary import path_resolver as pr

    original = pr.resolve_path
    def boom(*a, **k):
        raise RuntimeError("resolver exploded")
    pr.resolve_path = boom
    try:
        sbl = SystemBoundaryLayer(mode="enforce")
        decision = sbl.authorize_path(str(tmp_path / "x.txt"))
        # an internal error must surface as a BLOCK verdict
        assert decision.verdict == "BLOCK"
        assert decision.reason_code == "SBL_INTERNAL_ERROR"
    finally:
        pr.resolve_path = original


def test_exception_in_fingerprint_blocks(tmp_path):
    from agent.system_boundary.boundary import SystemBoundaryLayer
    from agent.system_boundary import fingerprint as fp

    original = fp.fingerprint_path
    def boom(*a, **k):
        raise RuntimeError("fingerprint exploded")
    fp.fingerprint_path = boom
    try:
        sbl = SystemBoundaryLayer(mode="enforce")
        decision = sbl.authorize_path(str(tmp_path / "x.txt"))
        assert decision.verdict == "BLOCK"
        assert decision.reason_code == "SBL_INTERNAL_ERROR"
    finally:
        fp.fingerprint_path = original


def test_unknown_mutation_never_passes():
    from agent.system_boundary.boundary import SystemBoundaryLayer

    sbl = SystemBoundaryLayer(mode="enforce")
    decision = sbl.authorize_command(
        command="opaque_thing --mangle /etc/x",
        tool_name="shell_exec",
        capability="SYSTEM_EXEC",
        cwd="/",
    )
    assert decision.verdict == "BLOCK"


# ── §60 property invariants (deterministic core) ────────────────────

def test_boundary_block_never_reaches_adapter():
    from agent.system_boundary.boundary import SystemBoundaryLayer

    sbl = SystemBoundaryLayer(mode="enforce")
    decision = sbl.authorize_command(
        command="systemctl --user restart hermes-gateway",
        tool_name="shell_exec", capability="SYSTEM_EXEC", cwd="/")
    assert decision.verdict == "BLOCK"
    assert decision.allow is False


def test_self_control_never_executes():
    from agent.system_boundary.boundary import SystemBoundaryLayer

    sbl = SystemBoundaryLayer(mode="enforce")
    for cmd in ("systemctl --user restart hermes-gateway",
                "pkill -f hermes-gateway"):
        d = sbl.authorize_command(
            command=cmd, tool_name="shell_exec",
            capability="SYSTEM_EXEC", cwd="/")
        assert d.verdict == "BLOCK", cmd
