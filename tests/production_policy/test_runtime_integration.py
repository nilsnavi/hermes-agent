"""Sprint 1.3.8 — runtime integration: commit/rollback/idempotency/deny."""
from __future__ import annotations

import dataclasses
import json
import os

import pytest

from agent.production_policy.budget import DurableBudget
from agent.production_policy.exceptions import OperationNotAllowed, TargetNotRegistered
from agent.production_policy.models import TargetRegistration
from agent.production_policy.policy import PolicyEngine
from agent.production_policy.runtime import LimitedPolicyRuntime


def _engine(tmp_path, name="m"):
    e = PolicyEngine(target_store_dir=str(tmp_path / "store"))
    for pid in e.profiles:
        base = os.path.join(str(tmp_path), pid.lower())
        os.makedirs(base, exist_ok=True)
        e.profiles[pid] = dataclasses.replace(e.profiles[pid], enabled=True,
                                              exact_target_dir=base + "/")
        path = os.path.join(base, name + (".json" if "JSON" in pid else ""))
        e.targets[pid][name] = TargetRegistration(
            profile_id=pid, target_id=name, resolved_path=path,
            realpath=path, owner="hermes", mode=0o600)
    return e, base


def _appr(profile, op, target="m", phash="h"):
    return {"profile": profile, "profile_version": 1, "operation": op,
            "target": target, "payload_hash": phash, "expires_ts": 2 ** 40}


def _rt(tmp_path, name="m"):
    e, base = _engine(tmp_path, name)
    store = str(tmp_path / "rt")
    rt = LimitedPolicyRuntime(engine=e, store_dir=store,
                              resolved={name: e.targets["P1-MARKER"][name].resolved_path},
                              idem_path=str(tmp_path / "idem.json"), health_ok=lambda: True)
    return rt, e


def test_marker_commit(tmp_path):
    from agent.production_canary.atomic_write import content_hash
    rt, _ = _rt(tmp_path)
    payload = b"ENABLED"
    ph = content_hash(payload)
    r = rt.run(profile_id="P1-MARKER", target="m", operation="set_marker",
               payload=payload, approval=_appr("P1-MARKER", "set_marker", phash=ph),
               resource_mode="limited")
    assert r["status"] == "COMMITTED", r
    assert open(rt._target_path("m"), "rb").read() == payload
    # duplicate -> adapter=0
    calls = rt.adapter_calls
    r2 = rt.run(profile_id="P1-MARKER", target="m", operation="set_marker",
                payload=payload, approval=_appr("P1-MARKER", "set_marker", phash=ph),
                resource_mode="limited")
    assert r2["status"] == "DUPLICATE_ALREADY_COMMITTED"
    assert rt.adapter_calls == calls


def test_rollback_byte_for_byte(tmp_path):
    rt, _ = _rt(tmp_path)
    from agent.production_canary.atomic_write import content_hash
    p1 = b"ENABLED"
    rt.run(profile_id="P1-MARKER", target="m", operation="set_marker", payload=p1,
           approval=_appr("P1-MARKER", "set_marker", phash=content_hash(p1)),
           resource_mode="limited")
    before = open(rt._target_path("m"), "rb").read()
    p2 = b"DISABLED"
    r = rt.run(profile_id="P1-MARKER", target="m", operation="set_marker", payload=p2,
               approval=_appr("P1-MARKER", "set_marker", phash=content_hash(p2)),
               resource_mode="limited", fault_verify=True)
    assert r["status"] == "VERIFY_FAILED_ROLLED_BACK", r
    assert open(rt._target_path("m"), "rb").read() == before


def test_deny_unknown_operation_status(tmp_path):
    rt, _ = _rt(tmp_path)
    r = rt.run(profile_id="P1-MARKER", target="m", operation="system_restart",
               payload=b"x", approval=None, resource_mode="limited")
    # hard-denied op -> mapped to OperationNotAllowed status
    assert r["status"] == "OperationNotAllowed", r
    assert r["adapter_calls"] == 0


def test_deny_unresolved_target(tmp_path):
    rt, _ = _rt(tmp_path, name="m")
    r = rt.run(profile_id="P1-MARKER", target="ghost", operation="set_marker",
               payload=b"x", approval=None, resource_mode="limited")
    assert r["status"] == "TARGET_UNRESOLVED"
    assert r["adapter_calls"] == 0


def test_budget_exceeded_status(tmp_path):
    rt, e = _rt(tmp_path)
    from agent.production_canary.atomic_write import content_hash
    ph = content_hash(b"ENABLED")
    # exhaust attempt budget
    spec = e.profiles["P1-MARKER"].budget
    for _ in range(spec.max_attempts_per_hour):
        e._budget.record_attempt("P1-MARKER")
    r = rt.run(profile_id="P1-MARKER", target="m", operation="set_marker",
               payload=b"ENABLED", approval=_appr("P1-MARKER", "set_marker", phash=ph),
               resource_mode="limited")
    assert r["status"] == "BudgetExceeded", r
    assert r["adapter_calls"] == 0


def test_circuit_breaker_status(tmp_path):
    rt, e = _rt(tmp_path)
    from agent.production_canary.atomic_write import content_hash
    e._budget.bump("P1-MARKER", "consecutive_verify", 2)
    r = rt.run(profile_id="P1-MARKER", target="m", operation="set_marker",
               payload=b"ENABLED", approval=_appr("P1-MARKER", "set_marker",
                                                  phash=content_hash(b"ENABLED")),
               resource_mode="limited")
    assert r["status"] == "CircuitBreakerOpen", r
    assert r["adapter_calls"] == 0
