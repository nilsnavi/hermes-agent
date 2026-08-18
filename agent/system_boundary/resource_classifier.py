"""Resource classifier (Sprint 1.3.3 §10).

Deterministic classification of a resource from a resolved path.
Thin wrapper over path_resolver for the boundary layer; exists as a
separate module per the brief's module structure (§8).
"""

from .models import ResourceClass
from .path_resolver import ResolvedPath, resolve_path


class ResourceClassifier:
    """Deterministic resource classification (no LLM, no heuristics
    that can flip on phrasing)."""

    def classify(self, path: str, cwd: str = "/",
                 home: str = "/home/hermes") -> ResolvedPath:
        return resolve_path(path, cwd=cwd, home=home)

    def classify_resolved(
        self, resolved: ResolvedPath,
    ) -> ResourceClass:
        return resolved.resource_class


#: module-level convenience
classifier = ResourceClassifier()


def classify_path(path: str, cwd: str = "/") -> ResolvedPath:
    return resolve_path(path, cwd=cwd)


def classify_resolved(resolved: ResolvedPath) -> ResourceClass:
    return resolved.resource_class


__all__ = [
    "ResourceClassifier",
    "classifier",
    "classify_path",
    "classify_resolved",
    "ResourceClass",
]
