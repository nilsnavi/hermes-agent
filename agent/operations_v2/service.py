"""Operations service facade (Sprint 1.0.6.3) — one entry point.

Assembles the read-only inspector, the approval service, the manual
review reconstruction, the metrics aggregator and the health evaluator
over ONE database file. The ONLY mutation paths are explicit operator
approval decisions; everything else is read-only by construction.

Resume (approve → resume drill) is wired lazily through the canary
registry so this package stays importable without the gateway runtime.
"""

import os
from typing import Any, Callable, Dict, List, Optional

from .approval_service import ApprovalService
from .health import HealthEvaluator, HealthInputs
from .manual_review import ManualReviewOps
from .metrics import CanaryMetrics
from .models import (
    ApprovalDecision,
    ManualReviewItemDTO,
    OperatorIdentity,
    RunSummary,
    RunTimelineItem,
    RuntimeV2Health,
    StaleRun,
)
from .run_inspector import RunInspector


def _default_db() -> str:
    return os.path.expanduser("~/.hermes/state.db")


def _read_flags_dict() -> Dict[str, bool]:
    try:
        from agent.gateway_v2.flags import read_flags

        return read_flags().to_dict()
    except Exception:
        return {}


def _canary_side_effect(tool: Optional[str]) -> Optional[str]:
    """Side-effect class value for a tool, via the canary registry."""
    if not tool:
        return None
    try:
        from agent.execution.registry import SideEffectClass
        from agent.gateway_v2.canary import default_canary_registry

        reg = default_canary_registry()
        if not reg.has(tool):
            return None
        return reg.metadata(tool).side_effect_class.value
    except Exception:
        return None


class OperationsService:
    """Operator-facing operations surface for the read-only canary."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        flags: Optional[Dict[str, bool]] = None,
        gateway_alive_fn: Optional[Callable[[], bool]] = None,
        side_effect_fn: Optional[Callable[[Optional[str]], Optional[str]]] = None,
        runbook_path: Optional[str] = None,
        router_stats_fn: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        self._db = db_path or _default_db()
        self._flags = flags if flags is not None else _read_flags_dict()
        self._gateway_alive = gateway_alive_fn or _gateway_alive
        self._side_effect = side_effect_fn or _canary_side_effect
        self._runbook = runbook_path or os.path.expanduser(
            "~/.hermes/docs/hermes-v2/operator-runbook.md"
        )
        self._router_stats_fn = router_stats_fn or (lambda: {})
        self._inspector = RunInspector(self._db)
        self._approvals = ApprovalService(
            self._db, tool_side_effect_fn=self._side_effect
        )
        self._manual_review = ManualReviewOps(self._db)
        self._metrics = CanaryMetrics(self._db)
        self._health = HealthEvaluator()

    # ── runs ─────────────────────────────────────────────────────────

    def get_run(self, run_id: str) -> RunSummary:
        summary = self._inspector.get_run(run_id)
        self._enrich(summary)
        return summary

    def list_runs(self, **filters) -> List[RunSummary]:
        summaries = self._inspector.list_runs(**filters)
        for summary in summaries:
            self._enrich(summary)
        return summaries

    def timeline(self, run_id: str, **cursor) -> List[RunTimelineItem]:
        return self._inspector.get_run_timeline(run_id, **cursor)

    def incomplete_runs(self) -> List[RunSummary]:
        summaries = self._inspector.get_incomplete_runs()
        for summary in summaries:
            self._enrich(summary)
        return summaries

    def stale_runs(self, threshold_minutes: int = 60) -> List[StaleRun]:
        return self._inspector.get_stale_runs(threshold_minutes)

    # ── approvals ────────────────────────────────────────────────────

    def pending_approvals(self) -> List[Any]:
        return self._approvals.list_pending()

    def get_approval(self, approval_id: str, run_id: Optional[str] = None) -> Any:
        return self._approvals.get(approval_id, run_id)

    def approve(
        self,
        run_id: str,
        approval_id: str,
        operator: OperatorIdentity,
        expected_version: Optional[int] = None,
        note: Optional[str] = None,
    ) -> ApprovalDecision:
        return self._approvals.approve(
            run_id, approval_id, operator,
            expected_version=expected_version, note=note,
        )

    def reject(
        self,
        run_id: str,
        approval_id: str,
        operator: OperatorIdentity,
        expected_version: Optional[int] = None,
        note: Optional[str] = None,
    ) -> ApprovalDecision:
        return self._approvals.reject(
            run_id, approval_id, operator,
            expected_version=expected_version, note=note,
        )

    def expire(self, approval_id: str, run_id: Optional[str] = None) -> ApprovalDecision:
        return self._approvals.expire(approval_id, run_id=run_id)

    def approval_dry_run(
        self, run_id: str, approval_id: str, operator: OperatorIdentity,
        action: str = "approve",
    ) -> Dict[str, Any]:
        return self._approvals.dry_run(run_id, approval_id, operator, action)

    # ── manual review ────────────────────────────────────────────────

    def manual_reviews(self) -> List[ManualReviewItemDTO]:
        return self._manual_review.list_pending()

    # ── metrics / health ─────────────────────────────────────────────

    def metrics(self, window: str = "24h") -> Dict[str, Any]:
        return self._metrics.compute(window)

    def health(self) -> RuntimeV2Health:
        integrity = self._db_integrity()
        incomplete = self._inspector.get_incomplete_runs()
        waiting = self._approvals.list_pending()
        manual = self._manual_review.list_pending()
        stale = self._inspector.get_stale_runs(threshold_minutes=60)
        metrics = self._metrics.compute("all")
        try:
            from agent.intent_router.router import read_router_flags
            _ir_flags = read_router_flags()
        except Exception:
            _ir_flags = {"enabled": False, "mode": None}
        try:
            router_stats = self._router_stats_fn() or {}
        except Exception:
            router_stats = {}
        router_unsafe = int(router_stats.get("unsafe_predictions", 0) or 0)
        router_errors = int(router_stats.get("errors", 0) or 0)
        router_decisions = int(router_stats.get("decisions", 0) or 0)
        router_error_rate = (
            (router_errors / router_decisions) if router_decisions else None
        )

        inputs = HealthInputs(
            flags=self._flags,
            schema_ready=self._schema_ready(),
            gateway_alive=self._gateway_alive(),
            db_integrity=integrity,
            incomplete_runs=len(incomplete),
            waiting_approvals=len(waiting),
            manual_reviews=len(manual),
            stale_approval_count=sum(
                1 for s in stale if s.stale_reason == "STALE_APPROVAL"
            ),
            write_tools_executed=0,
            duplicate_responses=0,
            ordinary_traffic_v2=0,
            canary_failure_rate_high=(
                self._failure_rate_high(metrics)
            ),
            canary_allowlist_active=bool(self._flags.get("canary")),
            read_only_enforced=bool(self._flags.get("canary")),
            intent_router_enabled=bool(_ir_flags.get("enabled")),
            intent_router_mode=(
                _ir_flags.get("mode").value if _ir_flags.get("mode") else "off"
            ),
            router_error_rate=router_error_rate,
            unsafe_prediction_count=router_unsafe,
            router_decisions_total=router_decisions,
            kill_switch_flag_control=True,
            kill_switch_runbook_exists=os.path.exists(self._runbook),
            gateway_control_available=self._gateway_control_available(),
            slo_write_executions=0,
            slo_secret_findings=0,
        )
        health = self._health.evaluate(inputs)
        self._populate_canary_dates(health)
        return health

    # ── resume (approve → resume drill) ──────────────────────────────

    def resume(self, run_id: str, policy_override=None) -> Dict[str, Any]:
        """Exactly-once resume of an approved run (canary registry).

        Read-only canary surface only — the registry hides every write
        tool, so a resumed plan can never execute a write tool.

        *policy_override* (ExecutionPolicy) is for controlled operator
        drills ONLY (e.g. a stale run beyond its default runtime budget).
        The CLI never passes one — the default conservative policy
        stands unless an operator explicitly overrides it in code.
        """
        from agent.gateway_v2.canary import default_canary_registry
        from agent.orchestrator import RuntimeOrchestrator
        from agent.persistence import SQLiteExecutionStore

        registry = default_canary_registry()
        store = SQLiteExecutionStore(self._db)
        try:
            orchestrator = RuntimeOrchestrator(store, registry)
            result = orchestrator.resume(run_id, policy=policy_override)
            return {
                "run_id": result.run_id,
                "status": result.status,
                "stop_reason": (
                    result.stop_reason.value if result.stop_reason else None
                ),
                "tool_calls": result.tool_calls,
                "steps_executed": result.steps_executed,
                "failures": result.failures,
                "disposition": result.disposition,
                "error": result.error,
            }
        finally:
            store.close()

    # ── internals ────────────────────────────────────────────────────

    def _enrich(self, summary: RunSummary) -> None:
        """Fill stop_reason + recovery disposition from durable events."""
        timeline = self._inspector.get_run_timeline(summary.run_id, limit=1000)
        stop_reason = None
        for item in timeline:
            if item.event_type == "ORCHESTRATION_STOPPED":
                stop_reason = item.reason_code
        summary.stop_reason = stop_reason
        summary.recovery_disposition = self._disposition(summary.run_id)

    def _disposition(self, run_id: str) -> Optional[str]:
        try:
            from agent.persistence import SQLiteExecutionStore
            from agent.recovery.classifier import RecoveryClassifier

            store = SQLiteExecutionStore(self._db)
            try:
                run = store.get_run(run_id)
                return RecoveryClassifier(store).classify_run(run).value
            finally:
                store.close()
        except Exception:
            return None

    def _db_integrity(self) -> str:
        import sqlite3

        try:
            conn = sqlite3.connect(f"file:{self._db}?mode=ro", uri=True)
            try:
                row = conn.execute("PRAGMA integrity_check").fetchone()
                return "ok" if row and row[0] == "ok" else str(row[0])
            finally:
                conn.close()
        except Exception as exc:  # pragma: no cover
            return f"error: {exc}"

    def _schema_ready(self) -> bool:
        from agent.persistence.schema import ALL_TABLES

        import sqlite3

        try:
            conn = sqlite3.connect(f"file:{self._db}?mode=ro", uri=True)
            try:
                present = {
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                return all(t in present for t in ALL_TABLES)
            finally:
                conn.close()
        except Exception:
            return False

    @staticmethod
    def _failure_rate_high(metrics: Dict[str, Any]) -> bool:
        rate = metrics.get("canary_success_rate")
        terminal = metrics.get("canary_success_denominator", 0) or 0
        if rate is None or terminal < 5:
            return False  # too few samples — no false alarm
        return rate < 95.0

    def _gateway_control_available(self) -> bool:
        return self._gateway_alive()

    def _populate_canary_dates(self, health: RuntimeV2Health) -> None:
        """Last successful / failed canary run from the durable journal."""
        import sqlite3

        try:
            conn = sqlite3.connect(f"file:{self._db}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    "SELECT run_id, timestamp FROM agent_v2_events "
                    "WHERE event_type='RUN_COMPLETED' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    health.last_successful_canary_at = row[1]
                row = conn.execute(
                    "SELECT timestamp FROM agent_v2_events "
                    "WHERE event_type IN ('RUN_FAILED','TOOL_FAILED') "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    health.last_failed_canary_at = row[0]
            finally:
                conn.close()
        except Exception:
            pass


def _gateway_alive() -> bool:
    """Live gateway probe via systemctl (unit-level, never restart)."""
    import subprocess

    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "hermes-gateway.service"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False
