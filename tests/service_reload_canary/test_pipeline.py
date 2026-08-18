"""Sprint 1.3.10 — pipeline: shadow, idempotency, live commit (fake runner)."""
from __future__ import annotations

import os

from agent.service_reload_canary import (RegisteredService, ReloadBudget,
                                         ReloadTransaction, ServiceAllowlist)
from agent.service_reload_canary.flags import MODE, ENABLED


def _env(mode):
    return {MODE: mode, ENABLED: "true"}


def _mk(mode, tmp_path):
    al = ServiceAllowlist([RegisteredService("hermes-webui", "hermes-webui.service",
                                             "systemd", "user", "/usr/local/bin/hermes-webui",
                                             "hermes", "/bin/true", 1)])
    calls = {"n": 0}

    def fake_runner():
        calls["n"] += 1

    rt = ReloadTransaction(allowlist=al, budget=ReloadBudget(str(tmp_path / "b.json")),
                           mode_env=_env(mode), store_dir=str(tmp_path / "s"), runner=fake_runner,
                           identity_verified=True, graph_healthy=True, config_valid=True,
                           pre_healthy=True, approval_valid=True, reload_proven=True,
                           preflight_state={"identity_fp": "idf", "config_hash": "ch"})
    return rt, calls


def test_shadow_no_write(tmp_path):
    rt, calls = _mk("shadow", tmp_path)
    out = rt.run("hermes-webui", approved_intent="s1")
    assert "SHADOW" in out and "WRITE_0" in out
    assert getattr(rt, "_calls", {}).get("n", 0) == 0


def test_committed_adapter_one(tmp_path):
    rt, calls = _mk("canary", tmp_path)
    out = rt.run("hermes-webui", approved_intent="c1")
    assert out.startswith("COMMITTED") and "ADAPTER_1" in out


def test_idempotency_replay_adapter_zero(tmp_path):
    rt, calls = _mk("canary", tmp_path)
    out1 = rt.run("hermes-webui", approved_intent="idem")
    out2 = rt.run("hermes-webui", approved_intent="idem")
    assert "ADAPTER_1" in out1
    assert "DUPLICATE_ADAPTER_0" in out2


def test_non_allowlisted_denied(tmp_path):
    rt, calls = _mk("canary", tmp_path)
    out = rt.run("hermes-gateway")
    assert "SERVICE_NOT_ALLOWLISTED" in out


def test_canary_disabled(tmp_path):
    al = ServiceAllowlist([RegisteredService("hermes-webui", "hermes-webui.service",
                                             "systemd", "user", "x", "hermes", "/bin/true", 1)])
    rt = ReloadTransaction(allowlist=al, budget=ReloadBudget(None), mode_env={MODE: "off", ENABLED: "false"},
                           identity_verified=True, graph_healthy=True, config_valid=True,
                           pre_healthy=True, approval_valid=True, store_dir=str(tmp_path))
    assert "CANARY_DISABLED" in rt.run("hermes-webui")


def test_budget_exhausted(tmp_path):
    al = ServiceAllowlist([RegisteredService("hermes-webui", "hermes-webui.service",
                                             "systemd", "user", "x", "hermes", "/bin/true", 1)])
    b = ReloadBudget(str(tmp_path / "b2.json"))
    for _ in range(3):
        b.record_attempt()
    rt = ReloadTransaction(allowlist=al, budget=b, mode_env=_env("canary"),
                           identity_verified=True, graph_healthy=True, config_valid=True,
                           pre_healthy=True, approval_valid=True, store_dir=str(tmp_path))
    assert "BUDGET_EXCEEDED" in rt.run("hermes-webui", approved_intent="z")
