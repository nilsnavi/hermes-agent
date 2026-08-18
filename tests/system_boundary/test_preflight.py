"""Sprint 1.3.3 §21-§24/§63 — PREFLIGHT BINDING, REPLAY, EXPIRATION.

A preflight is cryptographically bound to tool + capability +
operation + effective action + canonical target + normalized args +
resource fingerprint + run/step context + graph version. Harmless
preflights can never be reused for a more dangerous operation.
"""

import pytest

from agent.system_boundary import preflight as pf
from agent.system_boundary import models as m


def _plan(**kw) -> m.SystemPreflightPlan:
    defaults = dict(
        preflight_id="pf-1",
        execution_id="ex-1",
        request_id="req-1",
        run_id="run-1",
        step_id="step-1",
        tool_name="systemctl",
        capability="SERVICE_CONTROL",
        operation_class="SERVICE_RESTART",
        effective_action_class="SERVICE_RESTART",
        canonical_targets=["nginx"],
        arguments_digest="args-nginx-restart",
        effective_risk="SYSTEM",
        risk_floor="SYSTEM",
        blast_radius="SERVICE",
        affected_services=["nginx"],
        graph_version="g1",
        graph_health="HEALTHY",
        created_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-01-02T00:00:00+00:00",
        preflight_digest="",
    )
    defaults.update(kw)
    return m.SystemPreflightPlan(**defaults)


def test_preflight_digest_binds_tool_and_target():
    d1 = pf.compute_preflight_digest(_plan())
    d2 = pf.compute_preflight_digest(
        _plan(canonical_targets=["ssh"]))          # restart ssh
    assert d1 != d2
    assert d1 != pf.compute_preflight_digest(
        _plan(operation_class="SERVICE_STOP"))      # stop nginx


def test_preflight_digest_binds_args():
    d1 = pf.compute_preflight_digest(_plan())
    d2 = pf.compute_preflight_digest(
        _plan(arguments_digest="args-nginx-restart-force"))
    assert d1 != d2


def test_preflight_digest_binds_run_step_context():
    d1 = pf.compute_preflight_digest(_plan())
    d2 = pf.compute_preflight_digest(_plan(run_id="run-2"))
    assert d1 != d2


def test_preflight_digest_binds_fingerprint():
    d1 = pf.compute_preflight_digest(_plan())
    d2 = pf.compute_preflight_digest(_plan(resource_fingerprints={
        "/etc/nginx/nginx.conf": {"inode": 1}}))
    assert d1 != d2


def test_preflight_digest_binds_graph_version():
    d1 = pf.compute_preflight_digest(_plan())
    d2 = pf.compute_preflight_digest(_plan(graph_version="g2"))
    assert d1 != d2


def test_preflight_digest_deterministic():
    d1 = pf.compute_preflight_digest(_plan())
    d2 = pf.compute_preflight_digest(_plan())
    assert d1 == d2
    assert len(d1) == 64  # sha256 hex


# ── §63 preflight replay ────────────────────────────────────────────

def test_replay_rejects_different_operation():
    """restart nginx preflight must reject stop nginx."""
    plan = _plan()
    assert pf.plan_matches(plan, operation_class="SERVICE_STOP",
                           canonical_targets=["nginx"]) is False


def test_replay_rejects_different_target():
    """restart nginx preflight must reject restart ssh."""
    plan = _plan()
    assert pf.plan_matches(plan, operation_class="SERVICE_RESTART",
                           canonical_targets=["ssh"]) is False


def test_replay_rejects_changed_args():
    plan = _plan()
    assert pf.plan_matches(plan, operation_class="SERVICE_RESTART",
                           canonical_targets=["nginx"],
                           arguments_digest="args-nginx-restart-extra") \
        is False


def test_replay_accepts_identical():
    plan = _plan()
    assert pf.plan_matches(plan, operation_class="SERVICE_RESTART",
                           canonical_targets=["nginx"],
                           arguments_digest="args-nginx-restart",
                           run_id="run-1", step_id="step-1") is True


def test_replay_rejects_different_run_when_not_reusable():
    plan = _plan()
    assert pf.plan_matches(plan, operation_class="SERVICE_RESTART",
                           canonical_targets=["nginx"],
                           arguments_digest="args-nginx-restart",
                           run_id="run-2", step_id="step-1",
                           reusable=False) is False


# ── §24 expiration ──────────────────────────────────────────────────

def test_expired_plan():
    plan = _plan()
    assert pf.is_expired(plan, now_iso="2099-01-01T00:00:00+00:00")


def test_fresh_plan_not_expired():
    plan = _plan()
    assert not pf.is_expired(plan, now_iso="2026-01-01T00:00:00+00:00")
