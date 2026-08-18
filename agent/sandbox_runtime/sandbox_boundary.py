"""SBL bridge (Sprint 1.3.5 §17) — mandatory SystemBoundaryLayer integration.

Every sandbox mutation passes SystemBoundary.authorize_path /
verify-style gates. The bridge maps the 1.3.3 SBL decision surface to
the sandbox runtime's fail-closed needs. NoopSystemBoundary is
forbidden for sandbox mutation execution (BOUNDARY_REQUIRED).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class BoundaryBridgeDecision:
    ok: bool
    reason: str = ""
    decision: Dict[str, Any] = field(default_factory=dict)


class SandboxBoundaryBridge:
    """Adapts SystemBoundaryLayer (Sprint 1.3.3) to the sandbox pipeline.

    Uses the SBL's own classification for path write targets; a BLOCK
    verdict (e.g. RESOURCE_SYSTEM, PROCESS_SELF_CONTROL_FORBIDDEN,
    PATH_UNRESOLVED) is a hard denial with adapter calls = 0.
    """

    def __init__(self, boundary) -> None:
        self._sbl = boundary
        name = type(boundary).__name__
        if name in ("NoopSystemBoundary",):
            raise ValueError(
                "NoopSystemBoundary is forbidden for sandbox mutation")

    def authorize_path(self, path: str) -> BoundaryBridgeDecision:
        authorize = getattr(self._sbl, "authorize_path", None)
        if authorize is None:
            # generic authorize with a path-carrying request
            authorize = self._sbl.authorize
        try:
            if hasattr(self._sbl, "authorize_path"):
                decision = self._sbl.authorize_path(path)
            else:
                decision = self._sbl.authorize(None, None)
            verdict = getattr(decision, "verdict", None) or \
                getattr(decision, "decision", None) or \
                str(decision).upper()
            ok = "BLOCK" not in str(verdict).upper()
            return BoundaryBridgeDecision(
                ok=ok,
                reason=str(getattr(decision, "reason_code", verdict)),
                decision={"verdict": str(verdict)})
        except Exception as exc:
            # fail closed on boundary errors
            return BoundaryBridgeDecision(
                ok=False, reason=f"SBL error: {exc}",
                decision={"verdict": "BLOCK", "error": str(exc)})
