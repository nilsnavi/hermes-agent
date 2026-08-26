"""Typed, bounded read-only capability allowlist (Phase 6 vertical).

Only these EXACT capability tokens may ever be admitted for a read-only agent
run in Phase 6. There is deliberately NO generic ``READ_ANYTHING``: the enum
vocabulary is closed, so a value outside it cannot even be expressed. A
capability here is METADATA/DECLARATION, never a grant -- actual read-only
execution is certified downstream by the SecurityBoundary + runtime-owned
admission.

Every token carries an access class (LOCAL_READ_ONLY / REMOTE_READ_ONLY /
NETWORK_OBSERVATION). REMOTE and NETWORK access is NOT auto-allowed just
because the operation is "read-only"; it requires an explicit, certified
provider (see network_policy). For the Phase 6 MVP only LOCAL read-only tokens
are granted by default.
"""

from __future__ import annotations

from enum import Enum

from agent.agent_security_boundary.status import SideEffectClass

_MAX_TEXT_LENGTH = 65_536


class CapabilityAccessClass(Enum):
    """Where/over what a read-only capability operates."""

    LOCAL_READ_ONLY = "local_read_only"          # local/synthetic sources only
    REMOTE_READ_ONLY = "remote_read_only"        # certified remote interface
    NETWORK_OBSERVATION = "network_observation"  # network observation (gated)


class ReadOnlyCapability(Enum):
    """Closed, typed read-only capability vocabulary (no READ_ANYTHING)."""

    READ_FILE_METADATA = "read_file_metadata"
    READ_TEXT_RESOURCE = "read_text_resource"
    SEARCH_INDEX = "search_index"
    READ_STATUS = "read_status"
    READ_HEALTH = "read_health"
    READ_CONFIGURATION_SUMMARY = "read_configuration_summary"
    READ_AUDIT_SUMMARY = "read_audit_summary"
    READ_MEMORY_CONTEXT = "read_memory_context"


# Canonical, frozen allowlist of read-only capability values (proof: no
# READ_ANYTHING / no wildcard can ever be represented).
READ_ONLY_ALLOWLIST: frozenset[ReadOnlyCapability] = frozenset(ReadOnlyCapability)

# Default access class per capability. Phase 6 MVP: everything is LOCAL (or a
# certified read interface). REMOTE/NETWORK are never auto-granted.
_DEFAULT_ACCESS = {
    ReadOnlyCapability.READ_FILE_METADATA: CapabilityAccessClass.LOCAL_READ_ONLY,
    ReadOnlyCapability.READ_TEXT_RESOURCE: CapabilityAccessClass.LOCAL_READ_ONLY,
    ReadOnlyCapability.SEARCH_INDEX: CapabilityAccessClass.LOCAL_READ_ONLY,
    ReadOnlyCapability.READ_STATUS: CapabilityAccessClass.LOCAL_READ_ONLY,
    ReadOnlyCapability.READ_HEALTH: CapabilityAccessClass.LOCAL_READ_ONLY,
    ReadOnlyCapability.READ_CONFIGURATION_SUMMARY: CapabilityAccessClass.LOCAL_READ_ONLY,
    ReadOnlyCapability.READ_AUDIT_SUMMARY: CapabilityAccessClass.LOCAL_READ_ONLY,
    ReadOnlyCapability.READ_MEMORY_CONTEXT: CapabilityAccessClass.LOCAL_READ_ONLY,
}

# Tokens that introduce a REMOTE/NETWORK access surface and therefore are
# NEVER admitted without an explicit certified provider (network policy).
_REMOTE_OR_NETWORK = frozenset(
    _cap for _cap, _cls in _DEFAULT_ACCESS.items()
    if _cls in (CapabilityAccessClass.REMOTE_READ_ONLY, CapabilityAccessClass.NETWORK_OBSERVATION)
)

# Phase 6 MVP ships no pre-certified remote/network capabilities: default deny.
NETWORK_READ_ONLY_DEFAULT_DENIED = True

assert not _REMOTE_OR_NETWORK, (
    "Phase 6 MVP must not pre-certify remote/network capabilities"
)


def access_class(capability: ReadOnlyCapability) -> CapabilityAccessClass:
    """Return the default access class for a capability (data only)."""
    if type(capability) is not ReadOnlyCapability:
        raise ValueError("capability must be an exact ReadOnlyCapability value")
    return _DEFAULT_ACCESS[capability]


def is_read_only_allowed(capability: object) -> bool:
    """True iff ``capability`` is one of the typed read-only tokens."""
    return type(capability) is ReadOnlyCapability and capability in READ_ONLY_ALLOWLIST


def side_effect_for(capability: ReadOnlyCapability) -> SideEffectClass:
    """All read-only capabilities classify as READ_ONLY (data, not grant)."""
    if type(capability) is not ReadOnlyCapability:
        raise ValueError("capability must be an exact ReadOnlyCapability value")
    return SideEffectClass.READ_ONLY


def describe(capability: ReadOnlyCapability) -> str:
    if type(capability) is not ReadOnlyCapability:
        raise ValueError("capability must be an exact ReadOnlyCapability value")
    return capability.value


__all__ = [
    "READ_ONLY_ALLOWLIST",
    "CapabilityAccessClass",
    "ReadOnlyCapability",
    "access_class",
    "describe",
    "is_read_only_allowed",
    "side_effect_for",
]