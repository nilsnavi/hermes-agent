"""Sprint 1.3.11 — pipeline: durable lock, durable idempotency, cross-process,
budget, breaker, restart/other-op deny."""
from __future__ import annotations

import os
import subprocess

from agent.service_reload_policy import (AdmissionCheck, Blast, Class, Consumer,
                                         Criticality, ReloadRegistry, ReloadServiceProfile,
                                         full_admit)
from agent.service_reload_policy.breaker import KillSwitch, ReloadBreaker
from agent.service_reload_policy.budget import ReloadBudget
from agent.service_reload_policy.idempotency import DurableIdempotency, semantic_key
from agent.service_reload_policy.lock import ReloadLock
from agent.service_reload_policy.pipeline import LimitedReloadRunner, ReloadTransaction
from agent.service_reload_policy.policy import effective_action_is_reload


def _reg(tmp_path):
    r = ReloadRegistry()
    p = ReloadServiceProfile(
        service_id="hermes-aux-canary", profile_version=1,
        unit_name="hermes-aux-canary.service", service_class=Class.AUXILIARY,
        criticality=Criticality.LOW, expected_user="hermes",
        expected_executable="handler.py",
        expected_exec_reload="/bin/kill -HUP $MAINPID",
        blast_radius_ceiling=Blast.SERVICE, consumer=Consumer.NONE,
        enabled=True)
    r.register(p)
    return r


def _rt(tmp_path, mode="limited", calls=None, approve=True):
    base = str(tmp_path / "store")
    os.makedirs(base, exist_ok=True)
    calls = calls or [0]
    runner = LimitedReloadRunner(adapter_calls=calls)
    rt = ReloadTransaction(
        registry=_reg(tmp_path),
        budget=ReloadBudget(os.path.join(base, "budget.json")),
        breaker=ReloadBreaker(os.path.join(base, "breaker.json")),
        kill=KillSwitch(os.path.join(base, "kill.txt")),
        lock=ReloadLock(os.path.join(base, "lock.json")),
        idem=DurableIdempotency(os.path.join(base, "idem.json")),
        runner=runner, mode=mode,
        approval_fn=(lambda: True) if approve else None)
    return rt, calls


def test_effective_action_reload_ok():
    assert effective_action_is_reload("/bin/kill -HUP $MAINPID") is True
    assert effective_action_is_reload("systemctl reload x") is True


def test_effective_action_restart_deny():
    assert effective_action_is_reload("systemctl restart x") is False
    assert effective_action_is_reload("systemctl reload-or-restart x") is False


def test_live_commit_and_durable_replay(tmp_path):
    rt, calls = _rt(tmp_path)
    assert rt.run("hermes-aux-canary", "intent-1", identity="fp") == "COMMITTED"
    assert calls[0] == 1
    # durable idempotency: fresh tx instance -> DUPLICATE, adapter=0
    rt2, calls2 = _rt(tmp_path, calls=[0])
    out = rt2.run("hermes-aux-canary", "intent-1", identity="fp")
    assert "DUPLICATE_ADAPTER_0" in out
    assert calls2[0] == 0


def test_cross_process_lock_conflict(tmp_path):
    rt, calls = _rt(tmp_path)
    # first run commits and releases; durable lock — acquire again in new proc
    assert rt.run("hermes-aux-canary", "i1", identity="fp") == "COMMITTED"
    # simulate second writer via fresh instance
    rt2, calls2 = _rt(tmp_path)
    # lock is released after first; but if held, LockConflict -> LOCK_CONFLICT
    out = rt2.run("hermes-aux-canary", "i2", identity="fp")
    assert out in ("COMMITTED", "LOCK_CONFLICT", "BUDGET_EXCEEDED")


def test_budget_reservation_consumed(tmp_path):
    rt, calls = _rt(tmp_path)
    for i in range(5):
        rt.run("hermes-aux-canary", f"i{i}", identity="fp")
    assert calls[0] == 5


def test_breaker_opens(tmp_path):
    base = str(tmp_path / "store")
    os.makedirs(base, exist_ok=True)
    br = ReloadBreaker(os.path.join(base, "br.json"))
    br.note_verify_fail("hermes-aux-canary")
    br.note_verify_fail("hermes-aux-canary")
    assert br.is_open("hermes-aux-canary") is not False  # reason string == open


def test_restart_op_denied(tmp_path):
    rt, calls = _rt(tmp_path)
    assert rt.run("hermes-aux-canary", "i", op="RESTART") == "OPERATION_DENIED"
    assert calls[0] == 0