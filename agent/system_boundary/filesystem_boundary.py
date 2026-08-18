"""Filesystem boundary (Sprint 1.3.3 §18).

Prevents: path traversal, symlink escape, parent symlink escape,
resource substitution, new-file parent escape, race between inspect
and execute. The TOCTOU race itself is handled by the fingerprint
re-check in verify_before_execute (preflight → execute revalidation).
"""

from . import path_resolver as pr
from .models import (
    ResourceClass,
    block_decision,
    pass_decision,
    revalidate_decision,
)

#: system resource classes that a mutation may never target
_FORBIDDEN_WRITE_CLASSES = frozenset({
    ResourceClass.SYSTEM_CONFIG,
    ResourceClass.SYSTEM_BINARY,
    ResourceClass.SYSTEM_SERVICE,
    ResourceClass.SYSTEM_STATE,
    ResourceClass.NETWORK_CONFIG,
    ResourceClass.PACKAGE_STATE,
    ResourceClass.SECRET_RESOURCE,
})


class FilesystemBoundary:
    """Fail-closed filesystem boundary for write-class operations."""

    def evaluate_write_target(self, path: str,
                              cwd: str = "/") -> object:
        """Classify a write target and decide.

        Returns a BoundaryDecision-like object with .verdict and
        .reason_code.
        """
        resolved = pr.resolve_path(path, cwd=cwd)
        if resolved.resolved is None and not resolved.exists:
            # new-file parent resolution failed → conservative block
            return block_decision("PATH_UNRESOLVED",
                                  resource_class=resolved
                                  .resource_class.value)
        if resolved.resource_class in _FORBIDDEN_WRITE_CLASSES:
            return block_decision("RESOURCE_SYSTEM",
                                  resource_class=resolved
                                  .resource_class.value,
                                  target_resources=[resolved.resolved])
        # symlink chains into system dirs are already reflected in the
        # resolved resource class; a chain alone is fine for user data
        return pass_decision("SBL_OK",
                             resource_class=resolved
                             .resource_class.value,
                             target_resources=[resolved.resolved])


__all__ = ["FilesystemBoundary"]
