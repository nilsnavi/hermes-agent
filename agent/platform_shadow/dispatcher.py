"""Shadow dispatcher (Phase 7 §2, §24).

Thin entrypoint over ``ShadowRuntime``. It re-validates that the input is an
exact ``ShadowTaskEnvelope`` (immutable DATA -- no credentials/tokens/adapters/
executors can exist in it) and applies the isolation guard before delegating.
It can never return/mutate a production object.
"""

from __future__ import annotations

from .exceptions import ShadowError
from .guards import IsolationGuard
from .models import ShadowDecision, ShadowTaskEnvelope
from .runtime import ShadowRunOutcome, ShadowRuntime


class ShadowDispatcher:
    """Validates + dispatches one shadow task copy (control plane only)."""

    __slots__ = ("_runtime",)

    def __init__(self, runtime: ShadowRuntime) -> None:
        self._runtime = runtime

    def dispatch(
        self,
        envelope: ShadowTaskEnvelope,
        production_decision: ShadowDecision | None = None,
    ) -> ShadowRunOutcome:
        if type(envelope) is not ShadowTaskEnvelope:
            raise ShadowError("envelope must be an exact ShadowTaskEnvelope value")
        # Mechanical isolation: any production-side callable smuggled in is rejected.
        for label, value in envelope.to_dict().items():
            IsolationGuard.reject_production_side(value, label)
        return self._runtime.dispatch(envelope, production_decision=production_decision)


__all__ = ["ShadowDispatcher"]