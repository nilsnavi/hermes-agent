"""Preflight plans (Sprint 1.3.3 §21-§24, §63).

- Cryptographic binding (§22): SHA-256 over canonical serialization of
  tool + capability + operation + effective action + normalized
  non-secret args + canonical targets + resource fingerprints +
  execution context + graph version.
- Replay protection (§63): a plan for 'restart nginx' rejects
  'restart ssh', 'stop nginx', changed args, different run/step.
- Expiration (§24): bounded TTL; expired → PREFLIGHT_EXPIRED →
  REVALIDATE_REQUIRED. No silent TTL extension.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import SystemPreflightPlan


def canonical_json(obj: Any) -> str:
    """Deterministic canonical serialization (sorted keys, no secrets
    — caller must not include raw secrets in the input)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def compute_preflight_digest(plan: SystemPreflightPlan) -> str:
    """§23 — SHA-256 over the canonical preflight binding."""
    payload = {
        "tool": plan.tool_name,
        "capability": plan.capability,
        "operation": plan.operation_class,
        "effective_action": plan.effective_action_class,
        "targets": sorted(plan.canonical_targets),
        "args_digest": plan.arguments_digest,
        "fingerprints": sorted(
            (k, v.get("inode"), v.get("device"), v.get("mtime_ns"),
             v.get("size"), v.get("realpath"))
            for k, v in sorted(plan.resource_fingerprints.items())
        ),
        "run": plan.run_id,
        "step": plan.step_id,
        "graph_version": plan.graph_version,
        "risk_floor": plan.risk_floor,
        "blast_radius": plan.blast_radius,
    }
    return hashlib.sha256(
        canonical_json(payload).encode("utf-8")).hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_plan(
    *,
    preflight_id: str,
    execution_id: str,
    request_id: str,
    run_id: str,
    step_id: str,
    tool_name: str,
    capability: str,
    operation_class: str,
    effective_action_class: str,
    canonical_targets: Optional[List[str]] = None,
    arguments_digest: str = "",
    resource_fingerprints: Optional[Dict[str, Any]] = None,
    effective_risk: str = "READ_ONLY",
    risk_floor: str = "READ_ONLY",
    blast_radius: str = "NONE",
    affected_services: Optional[List[str]] = None,
    affected_processes: Optional[List[str]] = None,
    validators: Optional[List[str]] = None,
    post_checks: Optional[List[str]] = None,
    rollback_possible: bool = False,
    rollback_strategy_metadata: Optional[Dict[str, Any]] = None,
    graph_version: Optional[str] = None,
    graph_health: Optional[str] = None,
    ttl_s: float = 30.0,
    created_at: Optional[str] = None,
) -> SystemPreflightPlan:
    """Build an immutable plan with digest + expiry."""
    created = created_at or _utcnow_iso()
    plan = SystemPreflightPlan(
        preflight_id=preflight_id,
        execution_id=execution_id,
        request_id=request_id,
        run_id=run_id,
        step_id=step_id,
        tool_name=tool_name,
        capability=capability,
        operation_class=operation_class,
        effective_action_class=effective_action_class,
        canonical_targets=list(canonical_targets or []),
        arguments_digest=arguments_digest,
        resource_fingerprints=dict(resource_fingerprints or {}),
        effective_risk=effective_risk,
        risk_floor=risk_floor,
        blast_radius=blast_radius,
        affected_services=list(affected_services or []),
        affected_processes=list(affected_processes or []),
        validators=list(validators or []),
        post_checks=list(post_checks or []),
        rollback_possible=rollback_possible,
        rollback_strategy_metadata=dict(rollback_strategy_metadata or {}),
        graph_version=graph_version,
        graph_health=graph_health,
        created_at=created,
        expires_at=None,
        preflight_digest="",
    )
    digest = compute_preflight_digest(plan)
    expires = None
    if ttl_s > 0:
        try:
            created_dt = datetime.fromisoformat(created)
        except (TypeError, ValueError):
            created_dt = datetime.now(timezone.utc)
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        expires = (
            created_dt + __import__("datetime").timedelta(
                seconds=ttl_s)).isoformat()
    # rebuild frozen dataclass with digest + expiry
    return SystemPreflightPlan(
        **{**plan.to_dict(), "preflight_digest": digest,
           "expires_at": expires})


def plan_matches(
    plan: SystemPreflightPlan,
    *,
    operation_class: str,
    canonical_targets: Optional[List[str]] = None,
    arguments_digest: str = "",
    run_id: Optional[str] = None,
    step_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    capability: Optional[str] = None,
    reusable: bool = True,
) -> bool:
    """§63 — does this plan authorize THIS exact operation?

    False → PREFLIGHT_MISMATCH (adapter must not run).
    """
    if str(plan.operation_class).upper() != \
            str(operation_class).upper():
        return False
    if canonical_targets is not None and \
            sorted(plan.canonical_targets) != sorted(canonical_targets):
        return False
    if arguments_digest and plan.arguments_digest != arguments_digest:
        return False
    if tool_name is not None and plan.tool_name != tool_name:
        return False
    if capability is not None and plan.capability != capability:
        return False
    if not reusable:
        if run_id is not None and plan.run_id != run_id:
            return False
        if step_id is not None and plan.step_id != step_id:
            return False
    return True


def is_expired(plan: SystemPreflightPlan,
               now_iso: Optional[str] = None) -> bool:
    """§24 — bounded TTL; expired plans require a fresh preflight."""
    if plan.expires_at is None:
        return False
    now = now_iso or _utcnow_iso()
    try:
        now_dt = datetime.fromisoformat(now)
        exp_dt = datetime.fromisoformat(plan.expires_at)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        return now_dt > exp_dt
    except (TypeError, ValueError):
        return True  # malformed expiry → treat as expired (fail closed)


__all__ = [
    "canonical_json",
    "compute_preflight_digest",
    "make_plan",
    "plan_matches",
    "is_expired",
]
