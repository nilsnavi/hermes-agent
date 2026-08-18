"""Sprint 1.3.10 — reload canary policy decision (fail-closed gates)."""
from __future__ import annotations

from .allowlist import RegisteredService
from .exceptions import (ReloadApprovalInvalid, ReloadBudgetExceeded,
                         ReloadCanaryDisabled, ReloadConfigInvalid,
                         ReloadGraphDrift, ReloadIdentityDrift, ReloadPreHealthFailure)


class GateResult:
    def __init__(self, ok: bool, reason: str = ""):
        self.ok = ok
        self.reason = reason


def full_gate(*, mode: str, enabled: bool, allowlisted, identity_verified: bool,
              graph_healthy: bool, blast_service: bool, config_valid: bool,
              pre_healthy: bool, approval_valid: bool, budget_ok: bool,
              exec_reload_proven: bool) -> GateResult:
    if mode != "canary" or not enabled:
        return GateResult(False, "CANARY_DISABLED")
    if not allowlisted:
        return GateResult(False, "SERVICE_NOT_ALLOWLISTED")
    if not identity_verified:
        return GateResult(False, "RELOAD_IDENTITY_DRIFT")
    if not graph_healthy:
        return GateResult(False, "RELOAD_GRAPH_DRIFT")
    if not blast_service:
        return GateResult(False, "BLAST_RADIUS_TOO_HIGH")
    if not config_valid:
        return GateResult(False, "RELOAD_CONFIG_INVALID")
    if not pre_healthy:
        return GateResult(False, "RELOAD_PRE_HEALTH_FAILED")
    if not approval_valid:
        return GateResult(False, "RELOAD_APPROVAL_INVALID")
    if not budget_ok:
        return GateResult(False, "BUDGET_EXCEEDED")
    if not exec_reload_proven:
        return GateResult(False, "EXECRELOAD_UNPROVEN")
    return GateResult(True)
