"""Sprint 1.3.7 §26 — sandbox rehearsal of the SAME production adapter contract
against a temporary mirror. Counts and asserts invariant-free behavior.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.production_canary.flags import Mode
from agent.production_canary.pipeline import ProductionCanaryPipeline
from agent.production_canary.deny import ProductionAdapter, ProductionAdapter as PA
from agent.production_canary.lock import LockConflict


def build(store, target, **kw):
    return ProductionCanaryPipeline(
        target=target, owner=os.getlogin(), mode=Mode.CANARY, enabled=True,
        baseline_sha="8dfe9b3c", store_dir=store, health_gate=lambda: [], **kw)


def main():
    root = tempfile.mkdtemp(prefix="canary-rehearsal-")
    d = os.path.join(root, "managed", "canary")
    os.makedirs(d, exist_ok=True)
    os.chmod(d, 0o700)
    target = os.path.join(d, "runtime-canary.json")
    store = os.path.join(root, "store")

    counters = {"success": 0, "rollback": 0, "deny": 0, "duplicate": 0,
                "concurrency_ok": 0, "crash": 0, "violations": 0}

    # --- 30 successful transactions (max_attempts high enough) ---
    p = build(store, target, max_attempts=200, max_mutations=200)
    for gen in range(1, 31):
        r = p.run(approve=True, generation=gen, canary_id=f"reh-{gen}")
        if r["status"] == "COMMITTED":
            counters["success"] += 1
        else:
            counters["violations"] += 1
            print("SUCCESS-FAIL", gen, r)

    # --- 10 rollback drills (fault_verify after write) ---
    for i in range(10):
        q = build(store, target, max_attempts=200, max_mutations=200)
        before = open(target, "rb").read() if os.path.exists(target) else b""
        r = q.run(approve=True, generation=100 + i, fault_verify=True)
        if r["status"] == "ROLLED_BACK":
            counters["rollback"] += 1
            if os.path.islink(target) or not os.path.exists(target):
                counters["violations"] += 1
            elif open(target, "rb").read() != before:
                counters["violations"] += 1
                print("ROLLBACK-RESTORE-FAIL", i)
        else:
            counters["violations"] += 1
            print("ROLLBACK-FAIL", i, r)

    # --- 10 denials (system-control / wrong op) ---
    for i in range(10):
        w = build(store + f"-d{i}", target, max_attempts=200, max_mutations=200)
        r = w.run(operation="SYSTEM_ACTION", approve=True)
        if r["status"] in ("DENIED", "BOUNDARY_BLOCKED"):
            counters["deny"] += 1
        else:
            counters["violations"] += 1
            print("DENY-FAIL", i, r)
        # also verify adapter not touched by deny ops
        if w.adapter.adapter_calls > 0:
            counters["violations"] += 1
            print("DENY-ADAPTER-CALL", i)

    # --- 5 duplicates (same idempotency key re-queued) ---
    for i in range(5):
        # use same pipeline + requeue_idem on the SAME generation
        e = build(store + f"-idem{i}", target, max_attempts=200, max_mutations=200)
        r1 = e.run(approve=True, generation=900 + i, requeue_idem=True)
        if r1["status"] != "COMMITTED":
            counters["violations"] += 1
            print("IDEM-FIRST-FAIL", i, r1)
        calls = e.adapter.adapter_calls
        r2 = e.run(approve=True, generation=900 + i, requeue_idem=True)
        if r2["status"] == "DUPLICATE_ALREADY_COMMITTED" and e.adapter.adapter_calls == calls:
            counters["duplicate"] += 1
        else:
            counters["violations"] += 1
            print("IDEM-FAIL", i, r2)

    # --- 5 concurrency (parallel writers on same resource -> exactly one wins) ---
    conc_root = tempfile.mkdtemp(prefix="canary-conc-")
    tgt = os.path.join(conc_root, "managed", "canary", "runtime-canary.json")
    os.makedirs(os.path.dirname(tgt), exist_ok=True)
    os.chmod(os.path.dirname(tgt), 0o700)
    for i in range(5):
        from agent.production_canary.lock import LockManager
        lm = LockManager(os.path.join(conc_root, f"locks{i}"), ttl_s=60)
        key = tgt
        results = []
        def worker(txid):
            try:
                lk = lm.acquire(key, txid, wait_s=0.1)
                try:
                    time.sleep(0.5)  # hold lock long enough to force overlap
                finally:
                    lm.release(lk)
                results.append("ok")
            except LockConflict:
                results.append("conflict")
        threads = [threading.Thread(target=worker, args=(f"tx-{i}-{j}",)) for j in range(3)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        if results.count("ok") == 1 and results.count("conflict") == 2:
            counters["concurrency_ok"] += 1
        else:
            counters["violations"] += 1
            print("CONC-FAIL", i, results)

    # --- 5 unknown-outcome / crash-recovery classification ---
    from agent.production_canary.rollback import classify_outcome, unknown_outcome_policy
    for i in range(5):
        oc = classify_outcome(execution_started=True, execution_completed=False)
        pol = unknown_outcome_policy(oc)
        if oc == "UNKNOWN_OUTCOME" and pol["retry"] == 0 and pol["manual_review"]:
            counters["crash"] += 1
        else:
            counters["violations"] += 1
            print("CRASH-FAIL", i, oc, pol)

    print("=== SANDBOX REHEARSAL ===")
    print(counters)
    ok = (counters["success"] == 30 and counters["rollback"] == 10 and
          counters["deny"] == 10 and counters["duplicate"] == 5 and
          counters["concurrency_ok"] == 5 and counters["crash"] == 5 and
          counters["violations"] == 0)
    print("INVARIANT_VIOLATIONS =", counters["violations"])
    print("REHEARSAL_PASS" if ok else "REHEARSAL_FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
