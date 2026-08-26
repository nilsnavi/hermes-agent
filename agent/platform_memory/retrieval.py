"""Retrieval pipeline.

The retrieval pipeline applies controls in a strict, ordered sequence before
any memory content reaches a model:

  1. tenant scope matrix (a query is bound to one tenant),
  2. permission filter  (MemoryAccess visibility: no cross-user/cross-tenant),
  3. redaction          (inline secrets stripped from payload),
  4. injection sanitation (directive markers treated as data -> drop/quarantine),
  5. similarity search  (semantic index yields candidate keys),
  6. Top-K              (bounded context handoff).

Every stage is fail-closed: a violating item is never passed downstream. The
pipeline returns plain DATA (redacted, non-authoritative context strings); it
cannot grant capability, approve execution, or modify policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .exceptions import MemoryInjectionDetected, MemoryScopeError
from .memory_scopes import MemoryAccess
from .memory_security import redact_secrets, sanitize_payload
from .storage_backends import MemoryQuery, StoredMemory


class CandidateSource(Protocol):
    """Provides raw candidate records for a tenant-scoped query."""

    def candidates(self, query: MemoryQuery) -> tuple[StoredMemory, ...]: ...


@dataclass(frozen=True, slots=True)
class ContextItem:
    key: str
    text: str            # redacted, sanitized, non-authoritative
    scope: str
    similarity: float


class RetrievalPipeline:
    """Ordered, fail-closed memory retrieval. No authority surface."""

    def __init__(self, source: CandidateSource, *, now: Callable[[], float]) -> None:
        self.source = source
        self.now = now

    def retrieve(
        self,
        *,
        access: MemoryAccess,
        query_text: str,
        top_k: int = 8,
    ) -> tuple[ContextItem, ...]:
        if type(access) is not MemoryAccess:
            raise MemoryScopeError("access must be an exact MemoryAccess value")
        if not isinstance(query_text, str) or not query_text.strip():
            raise MemoryScopeError("query_text must be a non-empty string")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1 or top_k > 32:
            raise MemoryScopeError("top_k must be an integer in [1, 32]")

        # Stage 1 & 2: scope matrix + permission filter baked into candidate query.
        query = MemoryQuery(
            tenant_id=access.tenant_id,
            scope="*",
            user_id=access.user_id,
            top_k=top_k,
        )
        candidates = self.source.candidates(query)

        # Similarity proxy stage (deterministic; pgvector seam supplies real scores).
        scored: list[tuple[float, StoredMemory, str]] = []
        for record in candidates:
            # permission filter: enforce MemoryAccess visibility (fail-closed)
            try:
                self._require_visible(access, record)
            except MemoryScopeError:
                continue
            # injection sanitation: directive marker -> drop (data-only evidence)
            try:
                sanitize_payload(record.payload)
            except MemoryInjectionDetected:
                continue
            # redaction: build redacted text once, use it for both scoring/output
            raw_text = self._render(record)
            text, _mod = redact_secrets(raw_text)
            scoring = self._trim(text)
            score = self._similarity(query_text, scoring)
            scored.append((score, record, text))

        scored.sort(key=lambda pair: -pair[0])
        return tuple(
            ContextItem(
                key=record.key,
                text=text,
                scope=record.scope,
                similarity=score,
            )
            for score, record, text in scored[:top_k]
        )

    def _require_visible(self, access: MemoryAccess, record: StoredMemory) -> None:
        # Enforce the full visibility matrix at the record boundary — never
        # rely solely on the store to have filtered tenant. Cross-tenant/cross-user
        # records are rejected fail-closed even if a wide driver returns them.
        if record.tenant_id != access.tenant_id:
            raise MemoryScopeError("cross-tenant memory access blocked")
        if record.scope not in ("global", "tenant", "user"):
            raise MemoryScopeError("invalid memory scope on record")
        if record.scope == "user" and record.user_id != access.user_id:
            raise MemoryScopeError("cross-user memory access blocked")

    def _render(self, record: StoredMemory) -> str:
        parts = [str(item) for item in record.payload]
        return " ".join(parts)

    def _trim(self, text: str) -> str:
        return text[:512]

    def _similarity(self, query: str, text: str) -> float:
        # Deterministic word-overlap proxy in [0,1]. At deployment the pgvector
        # seam supplies a real embedding score; this keeps the pipeline stdlib.
        q_tokens = {t for t in query.lower().split() if t}
        if not q_tokens:
            return 0.0
        t_tokens = set(text.lower().split())
        if not t_tokens:
            return 0.0
        return len(q_tokens & t_tokens) / len(q_tokens)