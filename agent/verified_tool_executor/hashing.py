"""Canonical hashing for the execution contract (Sprint 1.3.2 §16-§17).

Reuses the project's canonical redaction-then-hash helpers — the
executor does NOT invent a second hashing vocabulary:

- input_hash  = SHA-256(canonical SANITIZED input)  (§16)
- output_hash = SHA-256(canonical SANITIZED output) (§17)

Both hashes are computed on the SCRUBBED canonical JSON via
``agent.persistence.redaction`` — secrets are redacted BEFORE hashing,
so a digest can never disclose secret equality in telemetry
identifiers, and a hash never legitimizes storing plaintext (the
persisted receipt carries only scrubbed payloads + digests).
"""

from typing import Any, Dict, Optional

from agent.persistence.redaction import (
    compute_input_hash as _redaction_input_hash,
    compute_output_hash as _redaction_output_hash,
)


def compute_input_hash(arguments: Optional[Dict[str, Any]]) -> str:
    """Canonical SHA-256 of scrubbed tool arguments (§16)."""
    return _redaction_input_hash(arguments)


def compute_output_hash(output: Any) -> str:
    """Canonical SHA-256 of the scrubbed tool result (§17)."""
    return _redaction_output_hash(output)


__all__ = [
    "compute_input_hash",
    "compute_output_hash",
]
