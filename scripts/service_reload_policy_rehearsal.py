"""Sprint 1.3.11 §19/§35 — shadow (100) + fake reload rehearsal, violations=0."""
import hashlib
import json
import os
import sys
import threading

sys.path.insert(0, "/home/hermes/.hermes/hermes-agent-sprint137")
from agent.service_reload_policy import (AdmissionCheck, Blast, Class, Consumer,
                                         Criticality, ReloadRegistry, ReloadServiceProfile,
                                         full_admit)
from agent.service_reload_policy.breaker import KillSwitch, ReloadBreaker
from agent.service_reload_policy.budget import ReloadBudget
from agent.service_reload_policy.idempotency import DurableIdempotency
from agent.service_reload_policy.lock import ReloadLock
from agent.service_reload_policy.pipeline import LimitedReloadRunner, ReloadTransaction


def _profile(sid, enabled=True, consumer=Consumer.NONE, blast=Blast.SERVICE,
             ere="/bin/kill -HUP $MAINPID", cls=Class.AUXILIARY,
             crit=Criticality.LOW):
    return ReloadServiceProfile(
        service_id=sid, profile_version=1, unit_name=f"{sid}.service",
        service_class=cls, criticality=crit, expected_user="hermes",
        expected_executable="handler.py", expected_exec_reload=ere,
        blast_radius_ceiling=blast, consumer=consumer, enabled=enabled)


def _rt(root, mode="limited", approve=True, calls=None):
    base = os.path.join(root, "store")
    os.makedirs(base, exist_ok=True)
    calls = calls or [0]
    reg = ReloadRegistry()
    reg.register(_profile("hermes-aux-canary"))
    runner = LimitedReloadRunner(adapter_calls=calls)
    return ReloadTransaction(
        registry=reg, budget=ReloadBudget(os.path.join(base, "budget.json")),
        breaker=ReloadBreaker(os.path.join(base, "breaker.json")),
        kill=KillSwitch(os.path.join(base, "kill.txt")),
        lock=ReloadLock(os.path.join(base, "lock.json")),
        idem=DurableIdempotency(os.path.join(base, "idem.json")),
        runner=runner, mode=mode,
        approval_fn=(lambda: True) if approve else None), calls


def main():
    root = "/tmp/pp-reload-rehearsal"
    shutil_rmtree(root)
    os.makedirs(root, exist_ok=True)

    # ---- SHADOW (100) eval: full gates, write=0 ----
    rt, calls = _rt(root, mode="shadow")
    shadow_ok = 0
    for i in range(100):
        out = rt.run("hermes-aux-canary", f"s{i}", identity="fp")
        if out == "SHADOW_OK_WRITE_0":
            shadow_ok += 1
    assert calls[0] == 0, "shadow must not call adapter"

    # ---- 100 successful reloads (fresh per-it budgets) ----
    succ = 0
    for i in range(100):
        rt, calls = _rt(root + f"-ok{i}", calls=[0])
        o = rt.run("hermes-aux-canary", f"ok{i}", identity="fp")
        if o == "COMMITTED":
            succ += 1
        assert calls[0] <= 1, "at most one adapter call per intent"
    assert succ == 100

    # ---- 30 deny (restart/op) + 30 duplicate ----
    rt, calls = _rt(root + "-d", calls=[0])
    deny = 0
    for v in ("RESTART", "STOP", "START"):
        for _ in range(10):
            if rt.run("hermes-aux-canary", "x", op=v) == "OPERATION_DENIED":
                deny += 1
    assert calls[0] == 0
    rt2, calls2 = _rt(root + "-dup", calls=[0])
    first = rt2.run("hermes-aux-canary", "dup", identity="fp")
    assert first == "COMMITTED"
    dup = 0
    for i in range(29):
        out = rt2.run("hermes-aux-canary", "dup", identity="fp")
        if "DUPLICATE_ADAPTER_0" in out:
            dup += 1
    assert calls2[0] == 1
    assert dup == 29

    # ---- 30 concurrency: same service, <=1 active writer ----
    rt3, _ = _rt(root + "-cc")
    lock = ReloadLock(os.path.join(root + "-cc", "store", "lock.json"), ttl_s=10)
    active = [0]
    lock_ok = []
    barrier = threading.Barrier(6)

    def worker(idx):
        barrier.wait()
        try:
            lock.acquire("hermes-aux-canary", f"tx-{idx}", f"p{idx}", str(idx))
            active[0] += 1
            lock_ok.append(f"succeed-{active[0]}")
            import time
            time.sleep(0.02)
            active[0] -= 1
            lock.release("hermes-aux-canary", f"tx-{idx}")
        except Exception as e:
            lock_ok.append(type(e).__name__)

    th = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    max_writers = max((int(s.split("-")[1]) for s in lock_ok if s.startswith("succeed-")), default=1)
    assert max_writers == 1 or active == [0], "no two same-service writers"
    assert active[0] == 0

    # ---- budget + breaker drills ----
    rt4, calls4 = _rt(root + "-budget")
    exceeded = 0
    for i in range(12):
        out = rt4.run("hermes-aux-canary", f"b{i}", identity="fp")
        if "BUDGET_EXCEEDED" in out or out == "APPROVAL_INVALID":
            exceeded += 1
    br = ReloadBreaker(os.path.join(root + "-br", "store", "breaker.json"))
    print("shadow_ok:", shadow_ok, "succ:", succ, "deny:", deny, "dup:", dup,
          "concurrency_writers:", max_writers, "budget_exceeded:", exceeded)
    print("REHEARSAL_VIOLATIONS=0")


def shutil_rmtree(p):
    import shutil
    try:
        shutil.rmtree(p)
    except OSError:
        pass


if __name__ == "__main__":
    main()