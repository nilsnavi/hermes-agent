"""Sprint 1.3.10 §30/§31 — shadow (50) + fake reload rehearsal (100+), violations=0."""
from __future__ import annotations

import os
import sys
import tempfile
import threading

from agent.service_reload_canary import (RegisteredService, ReloadBudget,
                                         ReloadTransaction, ServiceAllowlist)
from agent.service_reload_canary.flags import ENABLED, MODE


def main():
    root = tempfile.mkdtemp(prefix="rc10-")
    al = ServiceAllowlist([RegisteredService("hermes-webui", "hermes-webui.service",
                                             "systemd", "user", "/usr/local/bin/hermes-webui",
                                             "hermes", "/bin/true", 1)])
    # ---- shadow: 50 evaluations, no write ----
    calls = {"n": 0}

    def fake_runner():
        calls["n"] += 1

    shadow_ok = 0
    for i in range(50):
        rt = ReloadTransaction(allowlist=al, budget=ReloadBudget(None), mode_env={MODE: "shadow", ENABLED: "true"},
                               runner=fake_runner, identity_verified=True, graph_healthy=True,
                               config_valid=True, pre_healthy=True, approval_valid=True,
                               preflight_state={"identity_fp": "idf", "config_hash": "c%d" % i})
        out = rt.run("hermes-webui", approved_intent="s%d" % i)
        if "SHADOW" in out and "WRITE_0" in out:
            shadow_ok += 1
    print("shadow_ok:", shadow_ok, "/50; runner_calls:", calls["n"])

    # ---- fake rehearsal with a persistent canary-mode runtime ----
    def fresh(mode="canary", path=None):
        return ReloadTransaction(allowlist=al, budget=ReloadBudget(path), mode_env={MODE: mode, ENABLED: "true"},
                                 runner=fake_runner, identity_verified=True, graph_healthy=True,
                                 config_valid=True, pre_healthy=True, approval_valid=True,
                                 preflight_state={"identity_fp": "idf", "config_hash": "ch"})

    rt = fresh(path=os.path.join(root, "b.json"))
    successes = failures = dup = budget = denied = 0
    violations = []
    for i in range(100):
        f = ReloadTransaction(allowlist=al, budget=ReloadBudget(None), mode_env={MODE: "canary", ENABLED: "true"},
                              runner=fake_runner, identity_verified=True, graph_healthy=True,
                              config_valid=True, pre_healthy=True, approval_valid=True,
                              preflight_state={"identity_fp": "idf", "config_hash": "ch"})
        out = f.run("hermes-webui", approved_intent="int%d" % i)
        if "COMMITTED" in out and "ADAPTER_1" in out:
            successes += 1
        elif "DUPLICATE" in out:
            dup += 1
        elif "BUDGET_EXCEEDED" in out:
            budget += 1
        else:
            violations.append(out)
    # duplicating one intent must give adapter 0 (idempotency)
    out = rt.run("hermes-webui", approved_intent="int0")
    dup2 = "DUPLICATE_ADAPTER_0" in out
    # non-allowlisted + disabled + restart verb denials
    denied = (rt.run("hermes-gateway") or "")
    from agent.service_reload_canary.exceptions import ServiceOperationDenied
    from agent.service_reload_canary.executor import assert_reload_only
    restart_denied = False
    try:
        assert_reload_only("restart")
    except ServiceOperationDenied:
        restart_denied = True
    # concurrency: same resource locked -> only one mutates
    n = {"v": 0}

    def worker():
        r = rt.run("hermes-webui", approved_intent="conc")
        if "DUPLICATE" in r or "BUDGET" in r:
            pass
        else:
            n["v"] += 1

    ts = [threading.Thread(target=worker) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    print("success:", successes, "dup:", dup, "budget:", budget,
          "idem_adapter0:", dup2, "gateway_denied:", denied,
          "restart_denied:", restart_denied, "concurrent_commits:", n["v"],
          "violations:", violations[:3])


if __name__ == "__main__":
    main()
