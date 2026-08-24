"""Sprint 1.3.16 — deterministic manual-review payload.  Read-only, no secrets.
Advisory commands are text only — never executable authority."""
from __future__ import annotations

from .models import ManualReviewPayload, RecoveryEvidence

_ALLOWED_CHILD_STATES = {
    "NOT_STARTED", "PREPARED", "SIMULATED_EXECUTED", "VERIFY_PENDING",
    "VERIFIED", "COMPENSATION_REQUIRED", "COMPENSATING", "COMPENSATED",
    "FAILED_SAFE", "UNKNOWN_OUTCOME", "TERMINAL",
}


def build_manual_review(evidence: RecoveryEvidence, *, crash_point: str,
                        child_states: dict[str, str],
                        unknown_outcomes: tuple[str, ...],
                        lock_digest: str, budget_digest: str,
                        approval_digest: str, compensation_status: str,
                        evidence_conflicts: tuple[str, ...],
                        recommended_action: str,
                        tx_id: str) -> ManualReviewPayload:
    # sanitize: only known child states, drop any caller-controlled junk
    clean_states = {
        k: v for k, v in child_states.items() if v in _ALLOWED_CHILD_STATES
    }
    return ManualReviewPayload(
        transaction_id=tx_id,
        service_set=tuple(evidence.service_set_digest.split(",")) if evidence.service_set_digest else (),
        last_known_phase=evidence.last_known_phase or crash_point,
        crash_point=crash_point,
        child_states=clean_states,
        unknown_outcomes=unknown_outcomes,
        lock_state_digest=lock_digest,
        budget_state_digest=budget_digest,
        approval_state_digest=approval_digest,
        compensation_status=compensation_status,
        evidence_conflicts=evidence_conflicts,
        recommended_operator_action=recommended_action,
    )


def payload_has_active_secrets(payload: ManualReviewPayload, secret_terms: tuple[str, ...] = ("password", "secret", "token", "bearer")) -> bool:
    """Guard: the manual review payload must never contain secrets."""
    text = str(payload).lower()
    return any(t in text for t in secret_terms)


__all__ = ["build_manual_review", "payload_has_active_secrets"]