"""Isolated Shadow Worker (Phase 8.3) — exceptions.

All worker errors are control-plane / worker-local.  NONE of them can ever
escape into or affect the production request path: the producer contract
(``transport.try_emit``) returns an outcome instead of raising, and the worker
runs in its own process with its own failure domain.
"""

from __future__ import annotations


class WorkerError(Exception):
    """Base error for the isolated shadow worker (never affects production)."""


class WorkerConfigError(WorkerError):
    """Invalid/unknown/missing worker configuration -> FAIL CLOSED."""


class EnvelopeValidationError(WorkerError):
    """Envelope failed strict validation (malformed, forbidden, oversized)."""


class UnknownEnvelopeSchema(EnvelopeValidationError):
    """schema_version is not the canonical known version -> DROP_FAIL_CLOSED."""

    def __init__(self, schema_version: object) -> None:
        self.schema_version = schema_version
        super().__init__(f"unknown envelope schema_version: {schema_version!r}")


class TransportUnavailable(WorkerError):
    """Producer could not reach the one-way transport (never raised to prod)."""


class WorkerKillSwitchEngaged(WorkerError):
    """SHADOW_KILL_SWITCH is ON; the worker refuses to process envelopes."""


class WorkerRuntimeError(WorkerError):
    """A worker/runtime step failed; recorded only, production unaffected."""


__all__ = [
    "EnvelopeValidationError",
    "TransportUnavailable",
    "UnknownEnvelopeSchema",
    "WorkerConfigError",
    "WorkerError",
    "WorkerKillSwitchEngaged",
    "WorkerRuntimeError",
]