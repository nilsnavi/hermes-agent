"""Sprint 1.3.13 — Single Aux Service Restart Canary (agent.service_restart_canary).

Extension of the Restart Foundation (1.3.12) that authorises exactly ONE
controlled restart for exactly ONE registered harmless Hermes auxiliary service:

    hermes-aux-canary.service

Authority is a NARROW typed capability (HERMES_AUX_SERVICE_RESTART_CANARY),
separate from reload authority. No implicit inheritance. No generic systemctl.
No public STOP / START / KILL / SIGNAL.

Pipeline:

    RestartFoundation → RestartCanaryPolicy → RestartPlan
        → ExactRestartExecutor → Verify → Stabilization → Commit

Deny paths (adapter=0):

    gateway         → SELF_CONTROL_FORBIDDEN
    unregistered    → NOT_REGISTERED
    stop/start      → OPERATION_DENIED
    kill/signal     → OPERATION_DENIED
    replay/dup      → DUPLICATE_ALREADY_COMMITTED
    generic systemctl → unavailable

Hard gates: kill-switch, budget (1 success / 2 attempts), circuit breaker,
durable idempotency, durable per-service lock, single-use approval, TTL.

In Sprint 1.3.13 production restart is limited to ONE canary restart after
explicit operator approval ("одобряю live restart"). Replay → adapter=0.
"""
from __future__ import annotations

__all__ = [
    "allowlist",
    "approval",
    "breaker",
    "budget",
    "cli",
    "events",
    "executor",
    "flags",
    "gateway",
    "idempotency",
    "lock",
    "manager",
    "models",
    "negative_matrix",
    "plan",
    "policy",
    "preflight",
    "recovery",
    "rehearsal",
    "shadow",
    "stabilization",
    "telemetry",
    "verify",
]
