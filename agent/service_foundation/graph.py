"""Sprint 1.3.9 — bounded dependency graph, provenance, graph health."""
from __future__ import annotations

import hashlib
import time

from .models import (BlastRadius, EdgeType, GraphStatus, Provenance)

MAX_DEPTH = 4
MAX_NODES = 100


class ServiceDependencyGraph:
    def __init__(self, edges: dict | None = None, built_at: float | None = None,
                 ttl_s: float = 300.0, partial: bool = False,
                 corrupt: bool = False, unresolved: int = 0, stale: bool = False) -> None:
        self.edges: dict[str, list] = edges if edges is not None else {}
        self.built_at: float = built_at if built_at is not None else time.time()
        self.ttl_s = ttl_s
        self.partial = partial
        self.corrupt = corrupt
        self.unresolved = unresolved
        self._stale = stale

    def add_edge(self, src: str, dst: str, etype: EdgeType, prov: Provenance) -> None:
        self.edges.setdefault(src, []).append({"to": dst, "type": etype.value, "provenance": prov.value})

    @property
    def node_count(self) -> int:
        return len(set(self.edges.keys()) | {e["to"] for v in self.edges.values() for e in v})

    def digest(self) -> str:
        raw = sorted((s, sorted((e["to"], e["type"], e["provenance"]) for e in es))
                     for s, es in self.edges.items())
        return hashlib.sha256(repr(raw).encode()).hexdigest()

    def status(self) -> GraphStatus:
        if self.corrupt:
            return GraphStatus.CORRUPT
        if self._stale or (time.time() - self.built_at) > self.ttl_s:
            return GraphStatus.STALE
        limit = self.node_count
        if limit > MAX_NODES:
            return GraphStatus.CORRUPT
        if self.partial or self.unresolved > 0:
            return GraphStatus.PARTIAL
        return GraphStatus.HEALTHY

    def depends_on(self, src: str, depth: int = 0) -> set:
        seen: set = set()
        if depth > MAX_DEPTH:
            return seen
        for e in self.edges.get(src, []):
            if e["to"] not in seen:
                seen.add(e["to"])
                seen |= self.depends_on(e["to"], depth + 1)
        return seen

    def has_dependents(self, svc: str) -> bool:
        return any(svc in [e["to"] for e in es] for es in self.edges.values())
