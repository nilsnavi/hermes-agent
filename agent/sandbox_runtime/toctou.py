"""TOCTOU guard (Sprint 1.3.5 §26) — resource changed after preflight."""

from __future__ import annotations

from .exceptions import ResourceChangedAfterPreflight
from .models import SandboxMutationRequest
from .preflight import compute_fingerprint


def verify_toctou(req: SandboxMutationRequest, sandbox_root,
                  preflight_fingerprint: str) -> None:
    """Second fingerprint check immediately before execution.

    Any drift → RESOURCE_CHANGED_AFTER_PREFLIGHT → adapter calls = 0.
    """
    current = compute_fingerprint(req, sandbox_root)
    if current != preflight_fingerprint:
        raise ResourceChangedAfterPreflight(
            f"resource changed after preflight for {req.target}: "
            f"fingerprint {preflight_fingerprint[:12]}… → {current[:12]}…")
