"""Exception hierarchy for the execution-boundary security gate.

All failures derive from ``SecurityBoundaryError``. A missing mandatory component
or a boundary error must be treated as a denial (fail-closed), never as a fallback
to allow.
"""


class SecurityBoundaryError(Exception):
    """Base error for the execution security boundary layer."""


class ComponentMissing(SecurityBoundaryError):
    """A mandatory pipeline component (policy/router/boundary/executor/sandbox) is absent."""


class SealViolation(SecurityBoundaryError):
    """An attempt to reach a runtime-owned sealed sandbox directly from the outside."""


class CallerVerdictRejected(SecurityBoundaryError):
    """A caller supplied a verdict/approval/verdict as if it were authority."""


class AdmissionDenied(SecurityBoundaryError):
    """Admission was refused (fail-closed reason)."""


class RegistryDrift(SecurityBoundaryError):
    """The registry snapshot changed since it was sealed (rebound/mutated registry)."""


class UnknownImplementation(SecurityBoundaryError):
    """An agent definition carries an implementation id outside the canonical set."""


__all__ = [
    "AdmissionDenied",
    "CallerVerdictRejected",
    "ComponentMissing",
    "RegistryDrift",
    "SealViolation",
    "SecurityBoundaryError",
    "UnknownImplementation",
]