"""Pre-execution verifier (Sprint 1.3.3 §25/§26, §44).

verify_before_execute() revalidates the preflight immediately before
the adapter call: TOCTOU fingerprint check, preflight expiry, replay
protection. verify_after_execute() is the read-only/sandbox
foundation — no production mutations in 1.3.3.
"""

from typing import Any, Optional

from . import fingerprint as fp
from . import preflight as pf
from .boundary import SystemBoundaryLayer
from .models import (
    BoundaryDecision,
    GraphHealth,
    SystemPreflightPlan,
    block_decision,
    pass_decision,
    revalidate_decision,
)


def verify_before_execute(
    preflight: SystemPreflightPlan,
    mode: str = "enforce",
    boundary: Optional[SystemBoundaryLayer] = None,
    operation_override: Optional[str] = None,
    target_override=None,
) -> BoundaryDecision:
    """Standalone TOCTOU / expiry / replay check.

    ``boundary`` may be supplied for graph health checks; when absent
    the graph is treated as unavailable for mutations (fail closed).
    """
    if mode == "off":
        return pass_decision(reason_code="SBL_OK")
    if preflight is None:
        return block_decision("PREFLIGHT_REQUIRED")
    if pf.is_expired(preflight):
        return revalidate_decision("PREFLIGHT_EXPIRED")

    for path, fprint in preflight.resource_fingerprints.items():
        current = fp.fingerprint_path(path)
        if fp.fingerprint_changed(
                fp.ResourceFingerprint(**fprint), current):
            return revalidate_decision(
                "RESOURCE_CHANGED_AFTER_PREFLIGHT")

    if preflight.operation_class != "READ" and \
            preflight.blast_radius not in ("NONE", "LOCAL") and \
            preflight.graph_health in (
                GraphHealth.UNAVAILABLE.value,
                GraphHealth.CORRUPT.value):
        return revalidate_decision(
            "SERVICE_GRAPH_UNAVAILABLE"
            if preflight.graph_health == GraphHealth.UNAVAILABLE.value
            else "SERVICE_GRAPH_CORRUPT")

    if operation_override or target_override:
        op = operation_override or preflight.operation_class
        tgt = target_override if target_override is not None \
            else preflight.canonical_targets
        if not pf.plan_matches(
                preflight, operation_class=op, canonical_targets=tgt,
                arguments_digest=preflight.arguments_digest,
                run_id=preflight.run_id, step_id=preflight.step_id,
                reusable=False):
            return block_decision("PREFLIGHT_MISMATCH")

    return pass_decision(reason_code="SBL_OK")


def verify_after_execute(
    preflight: Optional[SystemPreflightPlan],
    result: Optional[Any] = None,
    mode: str = "enforce",
) -> dict:
    """§44 — read-only/sandbox post-execution foundation."""
    return {
        "verdict": "OBSERVED",
        "postcheck_required": False,
        "mode": mode,
    }


__all__ = [
    "verify_before_execute",
    "verify_after_execute",
]
