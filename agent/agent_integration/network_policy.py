"""Network / remote read-only policy (Phase 6 §8).

Splits read-only access into LOCAL_READ_ONLY, REMOTE_READ_ONLY and
NETWORK_OBSERVATION, and enforces that REMOTE/NETWORK access is NEVER
auto-allowed merely because the operation is "read-only". Default is
NETWORK_READ_ONLY=DENIED until a separate, explicitly certified read interface
is bound. A certified interface is a runtime-owned provider that the control
plane has explicitly vetted; it is DATA-only binding, not an execution grant.
"""

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import (
    NETWORK_READ_ONLY_DEFAULT_DENIED,
    CapabilityAccessClass,
    ReadOnlyCapability,
    access_class,
)


class NetworkPolicyError(ValueError):
    """Raised on malformed network-policy input."""


@dataclass(frozen=True, slots=True)
class NetworkPolicyVerdict:
    """Immutable verdict: allowed as read-only, or denied with a reason."""

    allowed: bool
    access_class: CapabilityAccessClass | None
    reason: str


class NetworkReadOnlyPolicy:
    """Pure network-access classifier (data only, grants nothing)."""

    __slots__ = ("_certified",)

    def __init__(self, certified_read_interfaces: frozenset[ReadOnlyCapability] = frozenset()) -> None:
        if not isinstance(certified_read_interfaces, frozenset):
            raise NetworkPolicyError("certified_read_interfaces must be a frozenset")
        for cap in certified_read_interfaces:
            if type(cap) is not ReadOnlyCapability:
                raise NetworkPolicyError(
                    "certified_read_interfaces must hold exact ReadOnlyCapability values"
                )
        self._certified = frozenset(certified_read_interfaces)

    def certified(self) -> frozenset[ReadOnlyCapability]:
        """Which capabilities currently have a certified read interface."""
        return self._certified

    def allows(self, capability: ReadOnlyCapability) -> NetworkPolicyVerdict:
        if type(capability) is not ReadOnlyCapability:
            raise NetworkPolicyError("capability must be an exact ReadOnlyCapability value")
        cls = access_class(capability)
        if cls is CapabilityAccessClass.LOCAL_READ_ONLY:
            return NetworkPolicyVerdict(True, cls, "local read-only source is MVP-authorized")
        if cls in (CapabilityAccessClass.REMOTE_READ_ONLY, CapabilityAccessClass.NETWORK_OBSERVATION):
            if capability in self._certified:
                return NetworkPolicyVerdict(
                    True, cls, f"explicitly certified read interface for {capability.value}"
                )
            return NetworkPolicyVerdict(
                False,
                cls,
                "remote/network read-only requires a certified interface (default DENIED)",
            )
        return NetworkPolicyVerdict(False, cls, "unknown access class (fail-closed)")


__all__ = [
    "NETWORK_READ_ONLY_DEFAULT_DENIED",
    "CapabilityAccessClass",
    "NetworkPolicyError",
    "NetworkPolicyVerdict",
    "NetworkReadOnlyPolicy",
]