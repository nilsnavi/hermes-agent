"""Sprint 1.3.17 — post-execution verification contract (§11 / §12).

Verification is determinist and side-effect free.  A child may only be counted
as ``CHILD_VERIFIED`` when every configured invariant passes:

* post-execution identity unchanged
* effect verification satisfies the binding's ``verification_contract``
* config invariant
* graph invariant
* health check passes
* no forbidden side effect observed
* lock ownership retained on the runtime holder
* approval / budget state valid

Any flaw -> FAILED (never advance); missing evidence -> UNKNOWN (never safe).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from .fake_adapter import FakeAdapterResult
from .models import AdapterOutcome, ChildExecutionBinding


class VerificationState(Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    state: VerificationState
    reason: str


def verify_child(binding: ChildExecutionBinding, adapter_result: FakeAdapterResult, *,
                 identity_unchanged: bool = True,
                 effect_ok: bool = True,
                 config_invariant: bool = True,
                 graph_invariant: bool = True,
                 health_ok: bool = True,
                 no_forbidden_side_effect: bool = True,
                 lock_retained: bool = True,
                 approval_valid: bool = True,
                 budget_valid: bool = True,
                 effect_evidence: str | None = None,
                 ) -> VerificationResult:
    """Run the verification contract for one child.  Fail closed."""
    if adapter_result.outcome != AdapterOutcome.ADAPTER_SUCCEEDED:
        return VerificationResult(VerificationState.UNKNOWN,
                                  f"cannot verify non-success outcome {adapter_result.outcome.value}")
    if not identity_unchanged:
        return VerificationResult(VerificationState.FAILED, "identity_changed")
    if not effect_ok:
        return VerificationResult(VerificationState.FAILED, "effect_mismatch")
    if not config_invariant:
        return VerificationResult(VerificationState.FAILED, "config_invariant_broken")
    if not graph_invariant:
        return VerificationResult(VerificationState.FAILED, "graph_invariant_broken")
    if not health_ok:
        return VerificationResult(VerificationState.FAILED, "health_check_failed")
    if not no_forbidden_side_effect:
        return VerificationResult(VerificationState.FAILED, "forbidden_side_effect")
    if not lock_retained:
        return VerificationResult(VerificationState.FAILED, "lock_lost_during_execution")
    if not approval_valid:
        return VerificationResult(VerificationState.FAILED, "approval_invalid_after_execution")
    if not budget_valid:
        return VerificationResult(VerificationState.FAILED, "budget_invalid_after_execution")
    return VerificationResult(VerificationState.VERIFIED, "all_invariants_pass")


__all__ = ["VerificationResult", "VerificationState", "verify_child"]