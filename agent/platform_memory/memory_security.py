"""Memory security filtering.

Two controls gate every memory payload that reaches a model:

1. Redaction — strips inline secrets (bearer tokens, api keys, credentials)
   before a payload is eligible for retrieval.
2. Prompt-injection sanitation — treats embedded directives inside stored
   memory strictly as DATA: any payload that carries a control marker (e.g.
   "ignore previous instructions", "you are now") is flagged and never handed
   to a downstream consumer as instructions. Detection is conservative and
   always preserves the evidence (flagged, not silently mutated).
"""

from __future__ import annotations

import re

from .exceptions import MemoryInjectionDetected

# Conservative inline-secret markers for redaction.
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|api[_-]?key|access[_-]?token|secret)\s+[A-Za-z0-9_\-\.=]+"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|passwd)\s*[=:]\s*[A-Za-z0-9_\-\.=]+"),
)

# Directive markers that indicate a stored string is trying to steer a model.
_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "you are now",
    "you are not",
    "system prompt:",
    "disregard",
    "forget everything above",
    "reminder:",  # benign-looking but control-adjacent; conservative
)


def redact_secrets(text: str) -> tuple[str, bool]:
    """Redact inline secrets. Returns (redacted_text, changed)."""
    if not isinstance(text, str):
        return text, False
    changed = False
    for pattern in _SECRET_PATTERNS:
        new = pattern.sub("[REDACTED]", text)
        if new != text:
            text = new
            changed = True
    return text, changed


def sanitize_payload(payload: tuple[object, ...]) -> tuple[object, ...]:
    """Scan a payload tuple for injection markers.

    Detection is conservative: if ANY string element exhibits a directive
    marker, the whole payload is treated as data-only evidence — the caller
    must treat it as non-instructional. The raw record is never deleted; it is
    marked non-authoritative. Raises MemoryInjectionDetected so the retrieval
    pipeline can drop or quarantine the item rather than pass it downstream.
    """
    if not isinstance(payload, tuple):
        raise MemoryInjectionDetected("payload must be a tuple")
    low = " ".join(
        str(item).lower() for item in payload if isinstance(item, str)
    )
    for marker in _INJECTION_MARKERS:
        if marker in low:
            raise MemoryInjectionDetected(f"payload contains injection marker: {marker!r}")
    return payload