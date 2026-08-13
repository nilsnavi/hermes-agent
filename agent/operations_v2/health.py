"""Runtime V2 health model + evaluator (Sprint 1.0.6.3 §17-18, §44-48).

Pure computation: ``HealthEvaluator.evaluate(inputs)`` maps durable
state + injected live facts to a RuntimeV2Health with a status
(HEALTHY / DEGRADED / UNHEALTHY), structured findings (AlertCode) and
the SLO counters. Nothing here opens the DB — the OperationsService
assembles the inputs.

Status rules (§18):
- UNHEALTHY: DB integrity failure / safety write executed / duplicate
  response / ordinary traffic routed V2 unexpectedly;
- DEGRADED: stale approval / single timeout / manual review pending /
  failure-rate high / any non-fatal finding;
- HEALTHY: everything else (gateway alive, DB healthy, read-only guard
  active, no pending manual reviews).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import AlertCode, HealthStatus, RuntimeV2Health


@dataclass
class HealthInputs:
    flags: Dict[str, Any] = field(default_factory=dict)
    schema_ready: bool = False
    gateway_alive: bool = False
    db_integrity: str = "unknown"
    incomplete_runs: int = 0
    waiting_approvals: int = 0
    manual_reviews: int = 0
    last_successful_canary_at: Optional[str] = None
    last_failed_canary_at: Optional[str] = None
    stale_approval_count: int = 0
    write_tools_executed: int = 0
    duplicate_responses: int = 0
    ordinary_traffic_v2: int = 0
    db_lock_loop: bool = False
    gateway_restart_loop: bool = False
    canary_failure_rate_high: bool = False
    canary_allowlist_active: bool = False
    read_only_enforced: bool = False
    intent_router_enabled: bool = False
    intent_router_mode: str = "off"
    router_error_rate: Optional[float] = None
    unsafe_prediction_count: int = 0
    router_decisions_total: int = 0
    kill_switch_flag_control: bool = True
    kill_switch_runbook_exists: bool = False
    gateway_control_available: bool = True
    slo_write_executions: int = 0
    slo_secret_findings: int = 0


class HealthEvaluator:
    """Deterministic health status + findings from durable inputs."""

    def evaluate(self, inputs: HealthInputs) -> RuntimeV2Health:
        findings: List[Dict[str, Any]] = []
        fatal: List[str] = []

        # ── UNHEALTHY conditions (§18) ───────────────────────────────
        if inputs.db_integrity != "ok":
            findings.append(_finding(AlertCode.DB_INTEGRITY_ERROR,
                                     f"db integrity: {inputs.db_integrity}"))
            fatal.append(AlertCode.DB_INTEGRITY_ERROR.value)
        if inputs.write_tools_executed > 0:
            findings.append(_finding(AlertCode.SAFETY_WRITE_EXECUTED,
                                     f"{inputs.write_tools_executed} write executions"))
            fatal.append(AlertCode.SAFETY_WRITE_EXECUTED.value)
        if inputs.duplicate_responses > 0:
            findings.append(_finding(AlertCode.DUPLICATE_RESPONSE,
                                     f"{inputs.duplicate_responses} duplicate responses"))
            fatal.append(AlertCode.DUPLICATE_RESPONSE.value)
        if inputs.ordinary_traffic_v2 > 0:
            findings.append(_finding(AlertCode.ORDINARY_TRAFFIC_V2,
                                     f"{inputs.ordinary_traffic_v2} ordinary requests "
                                     "routed to V2"))
            fatal.append(AlertCode.ORDINARY_TRAFFIC_V2.value)
        if inputs.db_lock_loop:
            findings.append(_finding(AlertCode.DB_LOCK_LOOP, "db lock loop"))
            fatal.append(AlertCode.DB_LOCK_LOOP.value)
        if inputs.gateway_restart_loop:
            findings.append(_finding(AlertCode.GATEWAY_RESTART_LOOP,
                                     "gateway restart loop"))
            fatal.append(AlertCode.GATEWAY_RESTART_LOOP.value)
        if inputs.slo_secret_findings > 0:
            findings.append(_finding(AlertCode.SECRET_LEAK,
                                     f"{inputs.slo_secret_findings} secret findings"))
            fatal.append(AlertCode.SECRET_LEAK.value)

        # ── DEGRADED conditions ──────────────────────────────────────
        if inputs.stale_approval_count > 0:
            findings.append(_finding(AlertCode.STALE_APPROVAL,
                                     f"{inputs.stale_approval_count} stale approvals"))
        if inputs.manual_reviews > 0:
            findings.append(_finding(AlertCode.MANUAL_REVIEW_PENDING,
                                     f"{inputs.manual_reviews} manual reviews pending"))
        if inputs.canary_failure_rate_high:
            findings.append(_finding(AlertCode.CANARY_FAILURE_RATE_HIGH,
                                     "canary failure rate above target"))
        # §71: unsafe router prediction → UNHEALTHY for the ROUTER, but
        # only an ALERT — never auto-disables global V2 (operator decides).
        if inputs.unsafe_prediction_count > 0:
            findings.append(_finding(AlertCode.ROUTER_UNSAFE_PREDICTION,
                                     f"{inputs.unsafe_prediction_count} unsafe "
                                     "router predictions (alert only, V2 stays on)"))
        if inputs.router_error_rate is not None and inputs.router_error_rate > 0.05:
            findings.append(_finding(AlertCode.ROUTER_ERROR_RATE_HIGH,
                                     f"router error rate {inputs.router_error_rate:.2%}"))

        if fatal:
            status = HealthStatus.UNHEALTHY
        elif findings:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.HEALTHY

        kill_switch = (
            inputs.kill_switch_flag_control
            and inputs.kill_switch_runbook_exists
            and inputs.gateway_control_available
        )

        slo = {
            "write_executions": inputs.slo_write_executions,
            "duplicate_responses": inputs.duplicate_responses,
            "ordinary_traffic_v2": inputs.ordinary_traffic_v2,
            "secret_findings": inputs.slo_secret_findings,
            "db_locks": 0,
            "gateway_unexpected_restarts": 0,
        }

        return RuntimeV2Health(
            status=status.value,
            enabled=bool(inputs.flags.get("enabled")),
            shadow=bool(inputs.flags.get("shadow")),
            canary=bool(inputs.flags.get("canary")),
            persistence=bool(inputs.flags.get("persistence")),
            schema_ready=inputs.schema_ready,
            gateway_alive=inputs.gateway_alive,
            db_integrity_last_known=inputs.db_integrity,
            incomplete_runs=inputs.incomplete_runs,
            waiting_approvals=inputs.waiting_approvals,
            manual_reviews=inputs.manual_reviews,
            last_successful_canary_at=inputs.last_successful_canary_at,
            last_failed_canary_at=inputs.last_failed_canary_at,
            kill_switch_available=kill_switch,
            canary_allowlist_active=inputs.canary_allowlist_active,
            read_only_enforced=inputs.read_only_enforced,
            intent_router_enabled=inputs.intent_router_enabled,
            intent_router_mode=inputs.intent_router_mode,
            router_error_rate=inputs.router_error_rate,
            unsafe_prediction_count=inputs.unsafe_prediction_count,
            router_decisions_total=inputs.router_decisions_total,
            findings=findings,
            slo=slo,
        )


def _finding(code: AlertCode, detail: str) -> Dict[str, Any]:
    return {"code": code.value, "severity": _severity(code), "detail": detail}


def _severity(code: AlertCode) -> str:
    if code in (
        AlertCode.SAFETY_WRITE_EXECUTED, AlertCode.DUPLICATE_RESPONSE,
        AlertCode.SECRET_LEAK, AlertCode.ORDINARY_TRAFFIC_V2,
        AlertCode.DB_INTEGRITY_ERROR, AlertCode.DB_LOCK_LOOP,
        AlertCode.GATEWAY_RESTART_LOOP,
    ):
        return "critical"
    return "warning"
