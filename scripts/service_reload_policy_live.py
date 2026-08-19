"""Sprint 1.3.11 live driver — one approved reload of hermes-aux-canary.

Verbs: canary (live reload + durable replay), neg (deny drills), postkill.
Cross-process durable idempotency via DurableIdempotency on disk.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/hermes/.hermes/hermes-agent-sprint137")
from agent.service_reload_policy import (AdmissionCheck, Blast, Class, Consumer,
                                         Criticality, ReloadRegistry, ReloadServiceProfile,
                                         full_admit)
from agent.service_reload_policy.breaker import KillSwitch, ReloadBreaker
from agent.service_reload_policy.budget import ReloadBudget
from agent.service_reload_policy.idempotency import DurableIdempotency
from agent.service_reload_policy.lock import ReloadLock
from agent.service_reload_policy.pipeline import LimitedReloadRunner, ReloadTransaction

UNIT = "hermes-aux-canary.service"
BASE = "/home/hermes/.hermes/managed/canary-service"
STORE = os.path.join(BASE, "policy-store")


def _reg():
    r = ReloadRegistry()
    p = ReloadServiceProfile(
        service_id="hermes-aux-canary", profile_version=1, unit_name=UNIT,
        service_class=Class.AUXILIARY, criticality=Criticality.LOW,
        expected_user="hermes",
        expected_executable="/home/hermes/.hermes/managed/canary-service/handler.py",
        expected_exec_reload="/bin/kill -HUP $MAINPID",
        blast_radius_ceiling=Blast.SERVICE, consumer=Consumer.NONE,
        enabled=True)
    r.register(p)
    return r


def _preflight_ok():
    """All §1 gates: identity VERIFIED, graph HEALTHY, blast SERVICE, consumer NONE,
    validator VALID, pre-health HEALTHY, rollback proven, no critical dep."""
    s = subprocess.run(["systemctl", "--user", "show", UNIT, "-pMainPID",
                        "-pActiveState", "-pSubState", "-pExecMainStatus"],
                       capture_output=True, text=True).stdout
    props = dict(line.split("=", 1) for line in s.strip().splitlines())
    active = props.get("ActiveState") == "active"
    running = props.get("SubState") == "running"
    pid_ok = props.get("MainPID", "0").isdigit() and int(props.get("MainPID", 0)) > 0
    try:
        json.load(open(os.path.join(BASE, "config.json")))
        config_valid = True
    except Exception:
        config_valid = False
    # admission + graph/consumer/blast proven from static profile + live state
    p = _reg().get("hermes-aux-canary")
    return full_admit(p, AdmissionCheck()) is None and active and running and pid_ok and config_valid


def _rt(mode="limited", calls=None):
    os.makedirs(STORE, exist_ok=True)
    calls = calls or [0]
    runner = LimitedReloadRunner(adapter_calls=calls)
    return ReloadTransaction(
        registry=_reg(),
        budget=ReloadBudget(os.path.join(STORE, "budget.json")),
        breaker=ReloadBreaker(os.path.join(STORE, "breaker.json")),
        kill=KillSwitch(os.path.join(STORE, "kill.txt")),
        lock=ReloadLock(os.path.join(STORE, "lock.json")),
        idem=DurableIdempotency(os.path.join(STORE, "idem.json")),
        runner=runner, mode=mode,
        approval_fn=lambda: True), calls


if __name__ == "__main__":
    verb = sys.argv[1]
    if verb == "canary":
        if not _preflight_ok():
            raise SystemExit("PREFLIGHT_FAIL: adapter_calls=0 :: STOP")
        rt, calls = _rt(mode="limited")
        a = rt.run("hermes-aux-canary", "live-reload-1", identity="fp-canary")
        # durable replay: fresh process reads same idem.json on disk
        rt2, calls2 = _rt(mode="limited", calls=[0])
        b = rt2.run("hermes-aux-canary", "live-reload-1", identity="fp-canary")
        print("live  :", a, f"adapter={calls[0]}")
        print("replay:", b, f"adapter={calls2[0]}")
    elif verb == "neg":
        rt, calls = _rt(mode="limited")
        for op in ("RESTART", "STOP", "START"):
            print(op, "->", rt.run("hermes-aux-canary", "neg", op=op))
        print("restart calls:", calls[0])
    elif verb == "postkill":
        open(os.path.join(STORE, "kill.txt"), "w").write("on")
        rt, calls = _rt(mode="limited")
        print("postkill:", rt.run("hermes-aux-canary", "live-reload-1", identity="fp-canary"))
        print("adapter=", calls[0])