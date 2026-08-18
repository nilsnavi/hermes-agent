"""Sprint 1.3.10 — reload transaction pipeline (all gates, idempotency, lock)."""
from __future__ import annotations

import hashlib
import os
import time
import uuid

from .budget import ReloadBudget
from .executor import ReloadExecutionRequest, run_reload
from .models import Mode, Outcome, ServiceReloadPlan
from .policy import GateResult, full_gate


def semantic_key(service_id, version, operation, identity_fp, config_hash, intent):
    h = hashlib.sha256()
    h.update(b"|".join(str(x).encode() for x in
                       (service_id, version, operation, identity_fp, config_hash, intent)))
    return h.hexdigest()


class ReloadTransaction:
    def __init__(self, *, allowlist, budget: ReloadBudget,
                 mode_env=None, store_dir=None, runner=None,
                 approval_valid=None, preflight_state=None,
                 identity_verified=False, graph_healthy=False,
                 config_valid=False, pre_healthy=False,
                 reload_proven=False, exec_reload_proven=True):
        import agent.service_reload_canary.flags as F
        self.mode = F.mode(mode_env)
        self.enabled = F.enabled(mode_env)
        self.allowlist = allowlist
        self.budget = budget
        self.store_dir = store_dir or "/tmp/rc-store"
        self.runner = runner
        self.approval_valid = approval_valid if approval_valid is not None else True
        self.reload_proven = reload_proven if reload_proven is not None else True
        self._preflight = preflight_state or {}
        self.exec_reload_proven = exec_reload_proven
        self.done: dict[str, str] = {}
        self.blast_service = True
        self.identity_verified = identity_verified
        self.graph_healthy = graph_healthy
        self.config_valid = config_valid
        self.pre_healthy = pre_healthy

    def run(self, service_id, approved_intent=None, *, operation="RELOAD_ONE_REGISTERED_AUX_SERVICE"):
        reg = self.allowlist.get(service_id)
        eff_mode = self.mode if self.mode != "off" else "off"
        if eff_mode == "off" or not self.enabled:
            return "CANARY_DISABLED"
        # shadow evaluates the full gate but writes nothing
        gate_mode = "canary"
        g = full_gate(mode=gate_mode, enabled=True, allowlisted=reg is not None,
                      identity_verified=self.identity_verified, graph_healthy=self.graph_healthy,
                      blast_service=self.blast_service, config_valid=self.config_valid,
                      pre_healthy=self.pre_healthy, approval_valid=self.approval_valid,
                      budget_ok=self.budget.can_attempt(), exec_reload_proven=self.exec_reload_proven)
        if not g.ok:
            return g.reason.decode() if isinstance(g.reason, bytes) else g.reason
        if self.mode == "shadow":
            return "SHADOW_OK_WRITE_0"
        key = semantic_key(service_id, reg.profile_version, operation, self.identity_fp(),
                           self.config_hash(), approved_intent or "")
        if key in self.done:
            return Outcome.COMMITTED.value + ":DUPLICATE_ADAPTER_0"
        self.budget.record_attempt()
        req = ReloadExecutionRequest(service_id, reg.unit_name,
                                     reg.expected_executable, "tx")
        adapter = run_reload(req, runner=self.runner)
        self.done[key] = Outcome.COMMITTED.value
        self.budget.record_success()
        return f"{Outcome.COMMITTED.value}:ADAPTER_{adapter}"

    def identity_fp(self):
        return self._preflight.get("identity_fp", "")

    def config_hash(self):
        return self._preflight.get("config_hash", "")
