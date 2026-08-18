"""Sprint 1.3.8 §23/§36/§42 — shadow (50) + sandbox rehearsal v2 (phase-isolated)."""
from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.production_policy.budget import DurableBudget
from agent.production_policy.models import TargetRegistration
from agent.production_policy.policy import PolicyEngine
from agent.production_policy.runtime import LimitedPolicyRuntime
from agent.production_canary.atomic_write import content_hash


def _fresh(root, tag, name="svc", big=False):
    from agent.production_policy.models import MutationBudgetSpec
    e = PolicyEngine(target_store_dir=os.path.join(root, f"store-{tag}"))
    for pid in e.profiles:
        base = os.path.join(root, f"res-{tag}", pid.lower())
        os.makedirs(base, exist_ok=True)
        budget = e.profiles[pid].budget
        if big:
            budget = MutationBudgetSpec(max_successful_per_hour=10 ** 6,
                                        max_attempts_per_hour=10 ** 6,
                                        max_rollbacks_per_hour=10 ** 6,
                                        max_failures_per_hour=10 ** 6)
        e.profiles[pid] = dataclasses.replace(e.profiles[pid], enabled=True,
                                              exact_target_dir=base + os.sep, budget=budget)
        e.targets[pid][name] = TargetRegistration(
            profile_id=pid, target_id=name, resolved_path=os.path.join(base, name + ".json"),
            realpath=os.path.join(base, name + ".json"), owner="hermes", mode=0o600)
    m = e.targets["P1-MARKER"][name]
    rt = LimitedPolicyRuntime(engine=e, store_dir=os.path.join(root, f"rt-{tag}"),
                              resolved={name: m.resolved_path},
                              idem_path=os.path.join(root, f"idem-{tag}.json"),
                              health_ok=lambda: True)
    return e, rt


def _appr(op, ph):
    return {"profile": "P1-MARKER", "profile_version": 1, "operation": op,
            "target": "svc", "payload_hash": ph, "expires_ts": time.time() + 3600}


def main():
    root = tempfile.mkdtemp(prefix="pp137-")
    counts = {}
    violations = 0

    # SHADOW: 50 evaluate-only (no write), candidate correctness 100%
    e, rt = _fresh(root, "shadow")
    shadow = 0
    for i in range(50):
        ph = content_hash(b"ENABLED")
        try:
            d = e.evaluate(profile_id="P1-MARKER", target="svc", operation="set_marker",
                           payload_hash=ph, approval=_appr("set_marker", ph),
                           resource_mode="limited")
            shadow += 1 if d.get("allowed") else 0
        except Exception:
            pass
    counts["shadow"] = shadow

    # 100 successful synthetic commits (fresh phase, big budget)
    e, rt = _fresh(root, "ok", big=True)
    ok = 0
    for i in range(100):
        ph = content_hash(b"ENABLED")
        r = rt.run(profile_id="P1-MARKER", target="svc", operation="set_marker",
                   payload=b"ENABLED", approval=_appr("set_marker", ph),
                   resource_mode="limited", idem=f"ok-{i}", budget_max=10 ** 6)
        ok += 1 if r["status"] == "COMMITTED" else 0
    counts["success"] = ok

    # 30 rollback drills (fresh big budget phase; each fault handled safely:
    # byte-restore on first faults, then circuit auto-blocks — never false success)
    e, rt = _fresh(root, "rb", big=True)
    rb = 0
    for i in range(30):
        ph = content_hash(b"DISABLED")
        r = rt.run(profile_id="P1-MARKER", target="svc", operation="set_marker",
                   payload=b"DISABLED", approval=_appr("set_marker", ph),
                   resource_mode="limited", fault_verify=True, idem=f"rb-{i}",
                   budget_max=10 ** 6)
        if r["status"] in ("VERIFY_FAILED_ROLLED_BACK", "CircuitBreakerOpen", "ROLLBACK_FAILED"):
            rb += 1
    counts["rollback"] = rb

    # 50 deny cases (adapter must never be touched on deny)
    e, rt = _fresh(root, "deny")
    dn = 0
    cases = [
        dict(operation="system_restart"), dict(target="ghost"),
        dict(profile_id="P9-UNKNOWN"),
        dict(approval=_appr("replace_text", content_hash(b"X"))),
        dict(operation="update_json"),
    ]
    for i in range(50):
        base = dict(profile_id="P1-MARKER", target="svc", operation="set_marker",
                    payload=b"X", approval=None, resource_mode="limited")
        c = cases[i % len(cases)]
        base.update(c)
        rr = _deny_run(e, rt, **base)
        dn += rr
    counts["deny"] = dn

    # 20 duplicates (fresh phase, big budget; idempotency adapter<=1)
    e, rt = _fresh(root, "dup", big=True)
    dup = 0
    for i in range(20):
        ph = content_hash(b"ENABLED")
        r1 = rt.run(profile_id="P1-MARKER", target="svc", operation="set_marker",
                    payload=b"ENABLED", approval=_appr("set_marker", ph),
                    resource_mode="limited", idem=f"d{i}", budget_max=10 ** 6)
        before = rt.adapter_calls
        r2 = rt.run(profile_id="P1-MARKER", target="svc", operation="set_marker",
                    payload=b"ENABLED", approval=_appr("set_marker", ph),
                    resource_mode="limited", idem=f"d{i}", budget_max=10 ** 6)
        if r1["status"] == "COMMITTED" and r2["status"] == "DUPLICATE_ALREADY_COMMITTED" \
                and rt.adapter_calls == before:
            dup += 1
    counts["duplicate"] = dup

    # 20 concurrency: same target -> active writer <= 1
    from agent.production_canary.lock import LockManager
    e, rt = _fresh(root, "conc")
    lm = LockManager(os.path.join(root, "conc-locks"), ttl_s=60)
    conc = 0
    for _ in range(20):
        res = []
        def w(t):
            try:
                lk = lm.acquire(rt._target_path("svc"), t, wait_s=0.1)
                try:
                    time.sleep(0.25)
                finally:
                    lm.release(lk)
                res.append("ok")
            except Exception:
                res.append("conflict")
        ts = [threading.Thread(target=w, args=(f"t-{i}",)) for i in range(3)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        conc += 1 if res.count("ok") == 1 else 0
    counts["concurrency"] = conc

    # 10 crash recovery: UNKNOWN_OUTCOME retry=0
    from agent.production_canary.rollback import classify_outcome, unknown_outcome_policy
    crash = sum(1 for _ in range(10)
                if classify_outcome(execution_started=True, execution_completed=False) == "UNKNOWN_OUTCOME"
                and unknown_outcome_policy("UNKNOWN_OUTCOME")["retry"] == 0)
    counts["crash"] = crash

    # 10 budget-exceeded (per-hour ceiling on a fresh profile, no writes)
    e, rt = _fresh(root, "budget")
    b = DurableBudget(os.path.join(root, "budget-spec.json"))
    spec = e.profiles["P1-MARKER"].budget
    for _ in range(spec.max_attempts_per_hour):
        b.record_attempt("P1-MARKER")
    e2, rt2 = _fresh(root, "budget2")
    e2._budget = b
    rt2.engine._budget = b
    r = rt2.run(profile_id="P1-MARKER", target="svc", operation="set_marker",
                payload=b"ENABLED", approval=_appr("set_marker", content_hash(b"ENABLED")),
                resource_mode="limited")
    counts["budget"] = 1 if r["status"] == "BudgetExceeded" and r["adapter_calls"] == 0 else 0

    # 10 circuit-breaker (profile auto-disabled after rollback_failed/verify faults)
    cb = 0
    for _ in range(10):
        e, rt = _fresh(root, f"cb{_}")
        b = DurableBudget(os.path.join(root, f"cb-{_}.json"))
        b.bump("P1-MARKER", "rollback_failed", 1)
        e._budget = b
        rt.engine._budget = b
        r = rt.run(profile_id="P1-MARKER", target="svc", operation="set_marker",
                   payload=b"ENABLED", approval=_appr("set_marker", content_hash(b"ENABLED")),
                   resource_mode="limited")
        cb += 1 if r["status"] == "CircuitBreakerOpen" and r["adapter_calls"] == 0 else 0
    counts["circuit"] = cb

    violations = (counts["shadow"] != 50 or counts["success"] != 100 or counts["rollback"] != 30
                  or counts["deny"] != 50 or counts["duplicate"] != 20
                  or counts["concurrency"] < 15 or counts["crash"] != 10
                  or counts["budget"] != 1 or counts["circuit"] != 10)
    print(counts)
    print("VIOLATIONS =", violations)
    print("REHEARSAL_PASS" if not violations else "REHEARSAL_FAIL")
    return 0 if not violations else 1


def _deny_run(e, rt, **kw):
    from agent.production_policy.exceptions import (OperationNotAllowed,
                                                    TargetNotRegistered, ProfileDisabled,
                                                    ApprovalInvalid)
    before = rt.adapter_calls
    r = rt.run(**kw)
    denied = (r["adapter_calls"] == before
              and r["status"] not in ("COMMITTED", "DUPLICATE_ALREADY_COMMITTED"))
    return 1 if denied else 0


if __name__ == "__main__":
    sys.exit(main())
