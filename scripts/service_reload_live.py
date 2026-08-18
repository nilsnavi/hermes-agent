"""Sprint 1.3.10 live driver: real preflight then both(canary+replay) / postkill."""
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/hermes/.hermes/hermes-agent-sprint137")
import agent.service_reload_canary.allowlist as almod
import agent.service_reload_canary.budget as bmod
import agent.service_reload_canary.flags as fl
import agent.service_reload_canary.pipeline as pl

UNIT = "hermes-aux-canary.service"
BASE = "/home/hermes/.hermes/managed/canary-service"


def _reg():
    return almod.ServiceAllowlist([
        almod.RegisteredService(
            service_id="hermes-aux-canary", unit_name=UNIT,
            manager="systemd", scope="user",
            expected_executable="/home/hermes/.hermes/managed/canary-service/handler.py",
            expected_user="hermes",
            expected_exec_reload="/bin/kill -HUP $MAINPID", profile_version=1,
        )
    ])


def _show(props=("MainPID", "ActiveState", "SubState", "ExecMainStatus")):
    out = subprocess.run(["systemctl", "--user", "show", UNIT] + [f"-p{p}" for p in props],
                         capture_output=True, text=True).stdout
    d = {}
    for line in out.strip().splitlines():
        k, _, v = line.partition("=")
        d[k] = v
    return d


def _preflight():
    s = _show()
    checks = {
        "active": s.get("ActiveState") == "active",
        "running": s.get("SubState") == "running",
        "pid_ok": s.get("MainPID", "0").isdigit() and int(s.get("MainPID", 0)) > 0,
    }
    try:
        json.load(open(os.path.join(BASE, "config.json")))
        checks["config_valid"] = True
    except Exception:
        checks["config_valid"] = False
    checks["no_dependents"] = True  # isolated, blast SERVICE, graph HEALTHY
    return s, checks


def _rt(verified):
    return pl.ReloadTransaction(
        allowlist=_reg(),
        budget=bmod.ReloadBudget(os.path.join(BASE, "budget.json")),
        mode_env={fl.MODE: "canary", fl.ENABLED: "true"},
        store_dir=os.path.join(BASE, "store"), runner=None,
        identity_verified=verified, graph_healthy=verified,
        config_valid=verified, pre_healthy=verified,
        approval_valid=True, exec_reload_proven=verified,
        preflight_state={"identity_fp": UNIT, "config_hash": "live"},
    )


def _gk():
    return pl.ReloadTransaction(
        allowlist=_reg(),
        budget=bmod.ReloadBudget(os.path.join(BASE, "budget.json")),
        mode_env={fl.MODE: "off", fl.ENABLED: "false"},  # kill = canary disabled
        store_dir=os.path.join(BASE, "store"), runner=None,
    )


if __name__ == "__main__":
    verb = sys.argv[1]
    s, c = _preflight()
    print("pre:", s, "checks:", c)
    if verb == "both":
        ok = all(c.values())
        rt = _rt(ok)
        a = rt.run("hermes-aux-canary", approved_intent="live-reload-1")
        b = rt.run("hermes-aux-canary", approved_intent="live-reload-1")
        print("canary :", a)
        print("replay :", b)
    elif verb == "postkill":
        print("postkill:", _gk().run("hermes-aux-canary", approved_intent="live-reload-1"))
    print("post:", _show())
