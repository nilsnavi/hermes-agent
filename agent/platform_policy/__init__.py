"""Platform policy contracts: deny-by-default, permissions, capability requests."""

from .capability import (
    CANONICAL_CAPABILITIES,
    CAPABILITY_TO_PERMISSION,
    CapabilityRequest,
    CapabilityRequestSet,
)
from .exceptions import DeniedOperation, InvalidPermission, PlatformPolicyError
from .permissions import (
    CANONICAL_PERMISSIONS,
    CAPABILITY_PERMISSION_ROLE,
    PermissionGrant,
    PlatformScope,
    intersect,
)
from .policy import DenyByDefaultPolicy, PolicyDecision, PolicyVerdict

__all__ = [
    "CANONICAL_CAPABILITIES",
    "CANONICAL_PERMISSIONS",
    "CAPABILITY_PERMISSION_ROLE",
    "CAPABILITY_TO_PERMISSION",
    "CapabilityRequest",
    "CapabilityRequestSet",
    "DeniedOperation",
    "DenyByDefaultPolicy",
    "InvalidPermission",
    "PermissionGrant",
    "PlatformPolicyError",
    "PlatformScope",
    "PolicyDecision",
    "PolicyVerdict",
    "intersect",
]