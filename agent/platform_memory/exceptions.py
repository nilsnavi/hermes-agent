"""Memory platform exceptions."""

from __future__ import annotations


class MemoryError(Exception):
    """Base error for the memory control plane."""


class MemoryScopeError(MemoryError):
    """Raised on illegal scope usage or cross-scope access."""


class MemoryNotFound(MemoryError):
    """Raised when a memory item key does not exist."""


class MemoryPermissionDenied(MemoryError):
    """Raised when a caller lacks permission for a memory operation."""


class MemoryStateError(MemoryError):
    """Raised on invalid memory lifecycle transitions."""


class MemoryInjectionDetected(MemoryError):
    """Raised when a memory payload carries suspected prompt-injection markers."""


class MemoryProvenanceError(MemoryError):
    """Raised when provenance cannot be established for an operation."""