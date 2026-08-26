"""Exceptions raised by platform policy contracts."""


class PlatformPolicyError(ValueError):
    """Base error for invalid platform policy contracts."""


class DeniedOperation(PlatformPolicyError):
    """Raised when an operation is not explicitly permitted (deny-by-default)."""


class InvalidPermission(PlatformPolicyError):
    """Raised when a permission name is unknown or malformed."""