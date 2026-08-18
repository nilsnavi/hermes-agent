"""System Boundary Layer — core orchestrator (Sprint 1.3.3 §1-§9, §26).

SystemBoundaryLayer is the real SystemBoundary implementation that
replaces NoopSystemBoundary in the VerifiedToolExecutor pipeline:

    preflight → authorize → verify_before_execute → adapter
               → verify_after_execute

Authority model (§2):
- CapabilityPolicyEngine remains the SOLE policy authority.
- VerifiedToolExecutor remains the SOLE execution gateway.
- The SBL may classify, compute effective actions, detect indirect
  execution, determine blast radius, RAISE risk, require approval /
  validation / fresh preflight, and BLOCK execution.
- The SBL may NEVER reduce risk, turn DENY into ALLOW, grant
  capability authority, approve, create permissions, bypass
  PolicyDecision or VerifiedToolExecutor, perform remediation or
  rollback.

Fail closed (§49): any unexpected exception inside an SBL component →
SBL_INTERNAL_ERROR → BLOCK. An exception can never become PASS.
"""

import hashlib
import uuid
from typing import Any, Dict, List, Optional

from . import effective_action as ea
from . import fingerprint as fp
from . import path_resolver as pr
from . import preflight as pf
from . import risk as risk_mod
from . import blast_radius as br_mod
from . import validation as val_mod
from .models import (
    BoundaryDecision,
    EffectiveActionClass,
    GraphHealth,
    OperationClass,
    ResourceClass,
    SystemPreflightPlan,
    block_decision,
    pass_decision,
    revalidate_decision,
)
from .exceptions import SBLInternalError, SBLBypassDetected

#: version of the boundary layer itself
SBL_VERSION = "sbl-1.3.3-v1"


class SystemBoundaryLayer:
    """Fail-closed System Boundary Layer over the execution pipeline.

    Modes (§55):
    - "off":     no enforcement, no classification (rollback path)
    - "shadow":  classify + audit, BLOCK critical mutations anyway
    - "enforce": full enforcement
    """

    BOUNDARY_VERSION = SBL_VERSION

    def __init__(
        self,
        mode: str = "shadow",
        graph=None,
        preflight_ttl_s: float = 30.0,
        gateway_pids: Optional[set] = None,
        gateway_services: Optional[List[str]] = None,
    ) -> None:
        self.mode = mode
        self.graph = graph
        self.preflight_ttl_s = preflight_ttl_s
        self.gateway_pids = gateway_pids or set()
        self.gateway_services = list(
            gateway_services or ["hermes-gateway", "hermes-gateway.service"])
        self._preflights: Dict[str, SystemPreflightPlan] = {}
        self._audit: List[Dict[str, Any]] = []
        self._validators = val_mod.ValidatorRegistry()

    # ── executor contract (§4) ──────────────────────────────────────

    def preflight(self, request, descriptor=None) -> SystemPreflightPlan:
        """Build the preflight plan for one execution request."""
        # classification from structured metadata (never the raw prompt)
        args = dict(getattr(request, "arguments", None) or {})
        command = args.get("command") or args.get("cmd") or ""
        cwd = str(args.get("cwd") or "/")
        tool_name = request.tool_name if hasattr(request, "tool_name") \
            else "unknown"
        capability = getattr(request, "capability", "") or ""

        if command:
            return self._preflight_command(command, tool_name,
                                           capability, cwd,
                                           request=request)
        # path-based target
        target = args.get("path") or args.get("target") or ""
        if target:
            return self._preflight_path(target, request=request)
        return self._preflight_generic(request)

    def authorize(self, request, descriptor=None,
                  preflight: Optional[SystemPreflightPlan] = None) \
            -> BoundaryDecision:
        """§5 — boundary verdict: PASS / BLOCK / REVALIDATE_REQUIRED.

        PASS is NOT permission — it only means the SBL adds no
        prohibition. Policy ALLOW is the executor's gate.
        """
        if self.mode == "off":
            return pass_decision(boundary_version=self.BOUNDARY_VERSION)
        try:
            plan = preflight or self.preflight(request, descriptor)
            # self-control by PID (§28) — process target is the gateway
            if plan.operation_class in (
                    OperationClass.PROCESS_KILL.value,
                    OperationClass.PROCESS_SIGNAL.value,
                    OperationClass.SERVICE_RESTART.value,
                    OperationClass.SERVICE_STOP.value,
                    OperationClass.SERVICE_START.value,
                    OperationClass.SERVICE_ENABLE.value,
                    OperationClass.SERVICE_DISABLE.value) \
                    and self._is_self_control(plan):
                return block_decision(
                    "PROCESS_SELF_CONTROL_FORBIDDEN",
                    boundary_version=self.BOUNDARY_VERSION,
                    operation_class=plan.operation_class,
                    effective_action_class=plan.effective_action_class,
                    risk_before=plan.effective_risk,
                    risk_floor=plan.risk_floor,
                    risk_after=plan.risk_floor,
                    blast_radius=plan.blast_radius,
                    affected_services=plan.affected_services,
                    affected_processes=plan.affected_processes,
                    preflight_digest=plan.preflight_digest,
                    graph_version=plan.graph_version,
                    graph_health=plan.graph_health,
                    confidence=0.99,
                )
            if plan.effective_action_class in (
                    EffectiveActionClass.PROCESS_SELF_CONTROL.value,
                    EffectiveActionClass.INDIRECT_SYSTEM_CONTROL.value):
                if self._is_self_control(plan):
                    return block_decision(
                        "PROCESS_SELF_CONTROL_FORBIDDEN",
                        boundary_version=self.BOUNDARY_VERSION,
                        resource_class=plan.resource_class
                        if hasattr(plan, "resource_class") else None,
                        operation_class=plan.operation_class,
                        effective_action_class=plan
                        .effective_action_class,
                        risk_before=plan.effective_risk,
                        risk_floor=plan.risk_floor,
                        risk_after=plan.risk_floor,
                        blast_radius=plan.blast_radius,
                        affected_services=plan.affected_services,
                        affected_processes=plan.affected_processes,
                        preflight_digest=plan.preflight_digest,
                        graph_version=plan.graph_version,
                        graph_health=plan.graph_health,
                        confidence=0.99,
                    )
            if plan.effective_action_class == \
                    EffectiveActionClass.UNKNOWN.value and \
                    plan.operation_class in ("UNKNOWN", "EXECUTE_SCRIPT",
                                             "EXECUTE_BINARY"):
                return block_decision(
                    "EFFECTIVE_ACTION_UNKNOWN",
                    boundary_version=self.BOUNDARY_VERSION,
                    operation_class=plan.operation_class,
                    effective_action_class=plan.effective_action_class,
                    risk_before=plan.effective_risk,
                    risk_floor="CRITICAL",
                    risk_after="CRITICAL",
                    blast_radius=plan.blast_radius,
                    preflight_digest=plan.preflight_digest,
                    graph_version=plan.graph_version,
                    graph_health=plan.graph_health,
                    confidence=0.8,
                )
            if plan.blast_radius in ("NETWORK", "UNKNOWN") and \
                    plan.operation_class not in ("READ",):
                return block_decision(
                    "BLAST_RADIUS_UNKNOWN"
                    if plan.blast_radius == "UNKNOWN"
                    else "BLAST_RADIUS_HIGH",
                    boundary_version=self.BOUNDARY_VERSION,
                    operation_class=plan.operation_class,
                    effective_action_class=plan.effective_action_class,
                    risk_before=plan.effective_risk,
                    risk_floor=plan.risk_floor,
                    risk_after=plan.risk_floor,
                    blast_radius=plan.blast_radius,
                    preflight_digest=plan.preflight_digest,
                    graph_version=plan.graph_version,
                    graph_health=plan.graph_health,
                )
            if plan.graph_health in (
                    GraphHealth.UNAVAILABLE.value,
                    GraphHealth.CORRUPT.value) and \
                    plan.operation_class not in ("READ",):
                return revalidate_decision(
                    "SERVICE_GRAPH_UNAVAILABLE"
                    if plan.graph_health == GraphHealth.UNAVAILABLE.value
                    else "SERVICE_GRAPH_CORRUPT",
                    boundary_version=self.BOUNDARY_VERSION,
                    operation_class=plan.operation_class,
                    effective_action_class=plan.effective_action_class,
                    risk_before=plan.effective_risk,
                    risk_floor=plan.risk_floor,
                    risk_after=plan.risk_floor,
                    blast_radius=plan.blast_radius,
                    preflight_digest=plan.preflight_digest,
                    graph_version=plan.graph_version,
                    graph_health=plan.graph_health,
                )
            if plan.validators and plan.operation_class not in ("READ",):
                for v in plan.validators:
                    if self._validators.validator_for(v) is None:
                        return block_decision(
                            "VALIDATION_UNAVAILABLE",
                            boundary_version=self.BOUNDARY_VERSION,
                            operation_class=plan.operation_class,
                            effective_action_class=plan
                            .effective_action_class,
                            risk_before=plan.effective_risk,
                            risk_after=plan.risk_floor,
                            blast_radius=plan.blast_radius,
                            preflight_digest=plan.preflight_digest,
                            graph_version=plan.graph_version,
                            graph_health=plan.graph_health,
                        )
            return pass_decision(
                boundary_version=self.BOUNDARY_VERSION,
                resource_class=plan.resource_class
                if hasattr(plan, "resource_class") else None,
                operation_class=plan.operation_class,
                effective_action_class=plan.effective_action_class,
                risk_before=plan.effective_risk,
                risk_floor=plan.risk_floor,
                risk_after=plan.risk_floor,
                blast_radius=plan.blast_radius,
                affected_services=plan.affected_services,
                affected_processes=plan.affected_processes,
                preflight_digest=plan.preflight_digest,
                graph_version=plan.graph_version,
                graph_health=plan.graph_health,
                confidence=0.95,
            )
        except SBLInternalError:
            raise
        except Exception:
            return block_decision(
                "SBL_INTERNAL_ERROR",
                boundary_version=self.BOUNDARY_VERSION)

    def verify_before_execute(
        self, request, descriptor=None,
        preflight: Optional[SystemPreflightPlan] = None,
        operation_override: Optional[str] = None,
        target_override: Optional[List[str]] = None,
    ) -> BoundaryDecision:
        """§25/§26 — revalidate immediately before adapter execution.

        Detects TOCTOU (fingerprint change), preflight expiry and
        preflight replay (operation/target mismatch).
        """
        if self.mode == "off":
            return pass_decision(boundary_version=self.BOUNDARY_VERSION)
        try:
            if preflight is None:
                return block_decision(
                    "PREFLIGHT_REQUIRED",
                    boundary_version=self.BOUNDARY_VERSION)
            if pf.is_expired(preflight):
                return revalidate_decision(
                    "PREFLIGHT_EXPIRED",
                    boundary_version=self.BOUNDARY_VERSION,
                    operation_class=preflight.operation_class,
                    effective_action_class=preflight
                    .effective_action_class,
                    risk_before=preflight.effective_risk,
                    risk_after=preflight.risk_floor,
                    blast_radius=preflight.blast_radius,
                    preflight_digest=preflight.preflight_digest,
                )
            # fingerprint re-check (TOCTOU §25)
            for path, fprint in preflight.resource_fingerprints.items():
                current = fp.fingerprint_path(path)
                if fp.fingerprint_changed(
                        fp.ResourceFingerprint(**fprint), current):
                    return revalidate_decision(
                        "RESOURCE_CHANGED_AFTER_PREFLIGHT",
                        boundary_version=self.BOUNDARY_VERSION,
                        operation_class=preflight.operation_class,
                        effective_action_class=preflight
                        .effective_action_class,
                        risk_before=preflight.effective_risk,
                        risk_after="CRITICAL",
                        blast_radius=preflight.blast_radius,
                        preflight_digest=preflight.preflight_digest,
                    )
            # graph health for mutations (§37): UNAVAILABLE/CORRUPT
            # graph can never prove safety → revalidate. Local file
            # mutations (radius NONE/LOCAL) don't depend on the graph.
            if preflight.operation_class != "READ" and \
                    preflight.blast_radius not in ("NONE", "LOCAL") and \
                    preflight.graph_health in (
                        GraphHealth.UNAVAILABLE.value,
                        GraphHealth.CORRUPT.value):
                return revalidate_decision(
                    "SERVICE_GRAPH_UNAVAILABLE"
                    if preflight.graph_health ==
                    GraphHealth.UNAVAILABLE.value
                    else "SERVICE_GRAPH_CORRUPT",
                    boundary_version=self.BOUNDARY_VERSION,
                    operation_class=preflight.operation_class,
                    effective_action_class=preflight
                    .effective_action_class,
                    risk_before=preflight.effective_risk,
                    risk_after=preflight.risk_floor,
                    blast_radius=preflight.blast_radius,
                    preflight_digest=preflight.preflight_digest,
                    graph_version=preflight.graph_version,
                    graph_health=preflight.graph_health,
                )
            # replay protection (§63)
            if operation_override or target_override:
                op = operation_override or preflight.operation_class
                tgt = target_override if target_override is not None \
                    else preflight.canonical_targets
                if not pf.plan_matches(
                        preflight, operation_class=op,
                        canonical_targets=tgt,
                        arguments_digest=preflight.arguments_digest,
                        run_id=preflight.run_id,
                        step_id=preflight.step_id,
                        reusable=False):
                    return block_decision(
                        "PREFLIGHT_MISMATCH",
                        boundary_version=self.BOUNDARY_VERSION,
                        operation_class=preflight.operation_class,
                        effective_action_class=preflight
                        .effective_action_class,
                        risk_before=preflight.effective_risk,
                        risk_after=preflight.risk_floor,
                        blast_radius=preflight.blast_radius,
                        preflight_digest=preflight.preflight_digest,
                    )
            return pass_decision(
                boundary_version=self.BOUNDARY_VERSION,
                operation_class=preflight.operation_class,
                effective_action_class=preflight.effective_action_class,
                risk_before=preflight.effective_risk,
                risk_after=preflight.risk_floor,
                blast_radius=preflight.blast_radius,
                preflight_digest=preflight.preflight_digest,
                graph_version=preflight.graph_version,
                graph_health=preflight.graph_health,
            )
        except Exception:
            return block_decision(
                "SBL_INTERNAL_ERROR",
                boundary_version=self.BOUNDARY_VERSION)

    def verify_after_execute(
        self, request, descriptor=None, result=None,
        preflight: Optional[SystemPreflightPlan] = None,
    ) -> Dict[str, Any]:
        """§44 — read-only/sandbox foundation for post-execution checks.

        Sprint 1.3.3 performs NO production mutations here; full
        transactional application is Sprint 1.3.4.
        """
        return {
            "verdict": "OBSERVED",
            "postcheck_required": False,
            "boundary_version": self.BOUNDARY_VERSION,
        }

    # ── command/path helpers (CLI + tests) ─────────────────────────

    def authorize_command(self, command: str, tool_name: str = "shell",
                          capability: str = "SYSTEM_EXEC",
                          cwd: str = "/") -> BoundaryDecision:
        try:
            plan = self._preflight_command(command, tool_name,
                                           capability, cwd)
            return self._decide_plan(plan)
        except Exception:
            # fail closed (§49): exception → SBL_INTERNAL_ERROR → BLOCK
            return block_decision(
                "SBL_INTERNAL_ERROR",
                boundary_version=self.BOUNDARY_VERSION)

    def preflight_path(self, path: str) -> SystemPreflightPlan:
        return self._preflight_path(path)

    def authorize_path(self, path: str) -> BoundaryDecision:
        """Boundary decision for a path write target (fail closed).

        System resources (SYSTEM_CONFIG/SYSTEM_BINARY/SYSTEM_STATE/
        NETWORK_CONFIG/SECRET_RESOURCE...) are hard-blocked for writes
        (§18/§19) — never a soft revalidate.
        """
        try:
            from .filesystem_boundary import FilesystemBoundary
            fb = FilesystemBoundary()
            fbs = fb.evaluate_write_target(path)
            if fbs.verdict == "BLOCK":
                return block_decision(
                    fbs.reason_code,
                    boundary_version=self.BOUNDARY_VERSION,
                    resource_class=fbs.resource_class,
                    target_resources=fbs.target_resources,
                    risk_before="READ_ONLY",
                    risk_after="SYSTEM",
                    blast_radius="HOST",
                )
            plan = self._preflight_path(path)
            return self._decide_plan(plan)
        except Exception:
            return block_decision(
                "SBL_INTERNAL_ERROR",
                boundary_version=self.BOUNDARY_VERSION)

    def preflight_command(self, command: str, tool_name: str,
                          capability: str, cwd: str) \
            -> SystemPreflightPlan:
        return self._preflight_command(command, tool_name, capability,
                                       cwd)

    def verify_command_preflight(
        self, preflight: SystemPreflightPlan) -> BoundaryDecision:
        return self.verify_before_execute(None, None, preflight)

    def call_adapter(self, adapter, context, arguments, token=None):
        """§46 — the ONLY sanctioned way to reach an adapter.

        Any adapter invocation without a valid SBL token is a
        BOUNDARY_BYPASS_DETECTED (fail closed).
        """
        from .guard import SBLGuardToken
        if not isinstance(token, SBLGuardToken) or token.sbl is not self:
            raise SBLBypassDetected(
                "BOUNDARY_BYPASS_DETECTED: adapter called outside the "
                "SystemBoundary pipeline")
        return adapter(context, arguments)

    # ── internals ──────────────────────────────────────────────────

    def _is_self_control(self, plan: SystemPreflightPlan) -> bool:
        for target in plan.canonical_targets:
            t = str(target).strip().lower().rstrip(".")
            for svc in self.gateway_services:
                if t == svc or t.startswith(svc):
                    return True
        for pid in plan.affected_processes:
            try:
                if int(pid) in self.gateway_pids:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _decide_plan(self, plan: SystemPreflightPlan) -> BoundaryDecision:
        """Direct decision over an already-built plan."""
        if self.mode == "off":
            return pass_decision(boundary_version=self.BOUNDARY_VERSION)
        try:
            # self-control by PID (kill <gateway_pid>) — the effective
            # action class stays PROCESS_KILL but the process target is
            # the gateway → forbidden (§28)
            if plan.operation_class in (
                    OperationClass.PROCESS_KILL.value,
                    OperationClass.PROCESS_SIGNAL.value,
                    OperationClass.SERVICE_RESTART.value,
                    OperationClass.SERVICE_STOP.value,
                    OperationClass.SERVICE_START.value,
                    OperationClass.SERVICE_ENABLE.value,
                    OperationClass.SERVICE_DISABLE.value) \
                    and self._is_self_control(plan):
                return block_decision(
                    "PROCESS_SELF_CONTROL_FORBIDDEN",
                    boundary_version=self.BOUNDARY_VERSION,
                    operation_class=plan.operation_class,
                    effective_action_class=plan.effective_action_class,
                    risk_before=plan.effective_risk,
                    risk_after=plan.risk_floor,
                    blast_radius=plan.blast_radius,
                    affected_services=plan.affected_services,
                    affected_processes=plan.affected_processes,
                    preflight_digest=plan.preflight_digest,
                    confidence=0.99,
                )
            if plan.effective_action_class in (
                    EffectiveActionClass.PROCESS_SELF_CONTROL.value,
                    EffectiveActionClass.INDIRECT_SYSTEM_CONTROL.value) \
                    and self._is_self_control(plan):
                return block_decision(
                    "PROCESS_SELF_CONTROL_FORBIDDEN",
                    boundary_version=self.BOUNDARY_VERSION,
                    operation_class=plan.operation_class,
                    effective_action_class=plan.effective_action_class,
                    risk_before=plan.effective_risk,
                    risk_after=plan.risk_floor,
                    blast_radius=plan.blast_radius,
                    affected_services=plan.affected_services,
                    affected_processes=plan.affected_processes,
                    preflight_digest=plan.preflight_digest,
                    confidence=0.99,
                )
            if plan.effective_action_class in (
                    EffectiveActionClass.PROCESS_SELF_CONTROL.value,
                    EffectiveActionClass.INDIRECT_SYSTEM_CONTROL.value):
                return block_decision(
                    "INDIRECT_SYSTEM_CONTROL",
                    boundary_version=self.BOUNDARY_VERSION,
                    operation_class=plan.operation_class,
                    effective_action_class=plan.effective_action_class,
                    risk_before=plan.effective_risk,
                    risk_after=plan.risk_floor,
                    blast_radius=plan.blast_radius,
                    preflight_digest=plan.preflight_digest,
                    confidence=0.98,
                )
            if plan.operation_class in (
                    OperationClass.UNKNOWN.value,) and \
                    plan.effective_action_class == \
                    EffectiveActionClass.UNKNOWN.value:
                return block_decision(
                    "EFFECTIVE_ACTION_UNKNOWN",
                    boundary_version=self.BOUNDARY_VERSION,
                    operation_class=plan.operation_class,
                    effective_action_class=plan.effective_action_class,
                    risk_before=plan.effective_risk,
                    risk_after="CRITICAL",
                    blast_radius=plan.blast_radius,
                    preflight_digest=plan.preflight_digest,
                    confidence=0.8,
                )
            if plan.operation_class not in ("READ",) and \
                    plan.blast_radius not in ("NONE", "LOCAL") and \
                    plan.graph_health in (
                        GraphHealth.UNAVAILABLE.value,
                        GraphHealth.CORRUPT.value):
                return revalidate_decision(
                    "SERVICE_GRAPH_UNAVAILABLE"
                    if plan.graph_health == GraphHealth.UNAVAILABLE.value
                    else "SERVICE_GRAPH_CORRUPT",
                    boundary_version=self.BOUNDARY_VERSION,
                    operation_class=plan.operation_class,
                    effective_action_class=plan.effective_action_class,
                    risk_before=plan.effective_risk,
                    risk_after=plan.risk_floor,
                    blast_radius=plan.blast_radius,
                    preflight_digest=plan.preflight_digest,
                    graph_version=plan.graph_version,
                    graph_health=plan.graph_health,
                )
            return pass_decision(
                boundary_version=self.BOUNDARY_VERSION,
                operation_class=plan.operation_class,
                effective_action_class=plan.effective_action_class,
                risk_before=plan.effective_risk,
                risk_after=plan.risk_floor,
                blast_radius=plan.blast_radius,
                affected_services=plan.affected_services,
                affected_processes=plan.affected_processes,
                preflight_digest=plan.preflight_digest,
                graph_version=plan.graph_version,
                graph_health=plan.graph_health,
                confidence=0.95,
            )
        except Exception:
            return block_decision(
                "SBL_INTERNAL_ERROR",
                boundary_version=self.BOUNDARY_VERSION)

    def _preflight_command(self, command: str, tool_name: str,
                           capability: str, cwd: str,
                           request=None) -> SystemPreflightPlan:
        result = ea.classify_command(command)
        op = result.operation_class.value
        eff = result.effective_action_class.value
        targets = list(result.targets)
        # gateway PID targets → self control
        processes: List[str] = []
        for t in targets:
            try:
                if int(t) in self.gateway_pids:
                    processes.append(t)
            except (TypeError, ValueError):
                pass
        radius = br_mod.blast_radius_for_target(
            targets[0] if targets else "", self.graph)
        floor = br_mod.risk_floor_for_radius(radius)
        if result.self_control:
            floor = risk_mod.apply_risk_floor(floor, "SYSTEM")
        run_id = getattr(request, "run_id", "") or "run-x"
        step_id = getattr(request, "step_id", "") or "step-x"
        request_id = getattr(request, "request_id", "") or "req-x"
        execution_id = uuid.uuid4().hex
        return pf.make_plan(
            preflight_id=uuid.uuid4().hex,
            execution_id=execution_id,
            request_id=request_id,
            run_id=run_id,
            step_id=step_id,
            tool_name=tool_name,
            capability=capability,
            operation_class=op,
            effective_action_class=eff,
            canonical_targets=targets,
            arguments_digest=hashlib.sha256(
                command.encode("utf-8")).hexdigest()[:32],
            effective_risk=floor,
            risk_floor=floor,
            blast_radius=radius,
            affected_services=(
                targets if result.is_system_control else []),
            affected_processes=processes,
            graph_version=(self.graph.graph_version
                           if self.graph else None),
            graph_health=(self.graph.health if self.graph
                          else GraphHealth.UNAVAILABLE.value),
            ttl_s=self.preflight_ttl_s,
        )

    def _preflight_path(self, path: str,
                        request=None) -> SystemPreflightPlan:
        resolved = pr.resolve_path(path)
        rc = resolved.resource_class.value
        fprint = fp.fingerprint_path(path)
        op = OperationClass.WRITE.value
        eff = EffectiveActionClass.WRITE_FILE.value
        radius = br_mod.blast_radius_for_target(
            resolved.resolved or path, self.graph) \
            if self.graph is not None else "LOCAL"
        floor = risk_mod.risk_floor_for_operation(op, rc)
        if rc in ("SYSTEM_CONFIG", "SYSTEM_BINARY", "SYSTEM_STATE",
                  "SYSTEM_SERVICE", "NETWORK_CONFIG",
                  "SECRET_RESOURCE"):
            floor = risk_mod.apply_risk_floor(floor, "SYSTEM")
        return pf.make_plan(
            preflight_id=uuid.uuid4().hex,
            execution_id=uuid.uuid4().hex,
            request_id=getattr(request, "request_id", "") or "req-x",
            run_id=getattr(request, "run_id", "") or "run-x",
            step_id=getattr(request, "step_id", "") or "step-x",
            tool_name=getattr(request, "tool_name", "") or "path",
            capability=getattr(request, "capability", "") or "",
            operation_class=op,
            effective_action_class=eff,
            canonical_targets=[resolved.resolved or path],
            arguments_digest=hashlib.sha256(
                path.encode("utf-8")).hexdigest()[:32],
            resource_fingerprints={
                path: fprint.to_dict()},
            effective_risk=floor,
            risk_floor=floor,
            blast_radius=radius,
            graph_version=(self.graph.graph_version
                           if self.graph else None),
            graph_health=(self.graph.health if self.graph
                          else GraphHealth.UNAVAILABLE.value),
            ttl_s=self.preflight_ttl_s,
        )

    def _preflight_generic(self, request) -> SystemPreflightPlan:
        op = str(getattr(request, "expected_side_effect", "READ_ONLY"))
        if op in ("READ_ONLY", "NONE"):
            return pf.make_plan(
                preflight_id=uuid.uuid4().hex,
                execution_id=uuid.uuid4().hex,
                request_id=getattr(request, "request_id", "") or "req-x",
                run_id=getattr(request, "run_id", "") or "run-x",
                step_id=getattr(request, "step_id", "") or "step-x",
                tool_name=getattr(request, "tool_name", "") or "",
                capability=getattr(request, "capability", "") or "",
                operation_class=OperationClass.READ.value,
                effective_action_class=EffectiveActionClass.READ.value,
                canonical_targets=[],
                effective_risk="READ_ONLY",
                risk_floor="READ_ONLY",
                blast_radius="NONE",
                graph_version=(self.graph.graph_version
                               if self.graph else None),
                graph_health=(self.graph.health if self.graph
                              else GraphHealth.UNAVAILABLE.value),
                ttl_s=self.preflight_ttl_s,
            )
        return pf.make_plan(
            preflight_id=uuid.uuid4().hex,
            execution_id=uuid.uuid4().hex,
            request_id=getattr(request, "request_id", "") or "req-x",
            run_id=getattr(request, "run_id", "") or "run-x",
            step_id=getattr(request, "step_id", "") or "step-x",
            tool_name=getattr(request, "tool_name", "") or "",
            capability=getattr(request, "capability", "") or "",
            operation_class=OperationClass.UNKNOWN.value,
            effective_action_class=EffectiveActionClass.UNKNOWN.value,
            canonical_targets=[],
            effective_risk="CRITICAL",
            risk_floor="CRITICAL",
            blast_radius="UNKNOWN",
            graph_version=None,
            graph_health=GraphHealth.UNAVAILABLE.value,
            ttl_s=self.preflight_ttl_s,
        )


__all__ = [
    "SystemBoundaryLayer",
    "SBL_VERSION",
]
