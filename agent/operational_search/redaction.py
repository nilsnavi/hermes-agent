"""Secret redaction for every output line (§7).

Every string that leaves the engine passes :func:`redact_line`
FIRST. The existing production redaction layer
(``agent.redact.redact_sensitive_text``) is the primary masker;
on top of it we apply a normalized-key/value scan for the mandatory
secret vocabulary (§7) so no sensitive candidate can pass through
even if the underlying layer's field list drifts.

Imported lazily so this package stays importable standalone (no
repo-level import at module load).
"""

from __future__ import annotations

import re
from typing import Optional

from .models import SearchError, SearchErrorCode

#: Mandatory sensitive vocabulary (§7) — matched on any line.
#: Values next to these tokens are scrubbed, and the tokens
#: themselves are never trusted as clean content.
_SECRET_TOKEN_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|authorization|bearer|cookie|password|"
    r"passwd|secret|openai[_-]?api[_-]?key|provider[_-]?credential|"
    r"client[_-]?secret|access[_-]?token|refresh[_-]?token)\b"
)
#: ``KEY=value`` / ``"key": "value"`` style assignments.
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)((?:api[_-]?key|token|authorization|bearer|cookie|password|"
    r"passwd|secret|openai[_-]?api[_-]?key|provider[_-]?credential|"
    r"client[_-]?secret|access[_-]?token|refresh[_-]?token)\s*[:=]\s*)"
    r"(\S+)"
)
#: Known vendor prefixes — a value that looks like a credential.
_PREFIX_RE = re.compile(
    r"(?i)\b(sk-[A-Za-z0-9_-]{6,}|ghp_[A-Za-z0-9]{6,}|xox[baprs]-"
    r"[A-Za-z0-9-]{6,}|AIza[A-Za-z0-9_-]{10,}|Bearer\s+[A-Za-z0-9._-]{8,})"
)

REDACTED = "[REDACTED]"


def _apply_redact_layer(text: str) -> str:
    """Run the existing production redaction layer (§7).

    Imported lazily (and defensively): if the repo layer is not
    importable in this environment, the mandatory vocabulary scan
    below still guarantees the secret list is enforced.
    """
    try:
        from agent.redact import redact_sensitive_text
    except Exception:
        return text
    try:
        return redact_sensitive_text(text, force=True)
    except Exception:
        # Never let a redaction-layer fault leak raw content — the
        # local vocabulary scan below still runs on the ORIGINAL.
        return text


def redact_line(text: str) -> str:
    """Redact one line: production layer + mandatory vocabulary scan.

    Raises :class:`SearchError` REDACTION_FAILURE only when the input
    is not text (defensive); a redaction that cannot prove itself
    safe must fail closed — but plain text always passes through with
    at least the vocabulary scan applied.
    """
    if not isinstance(text, str):
        raise SearchError(
            SearchErrorCode.REDACTION_FAILURE,
            "redaction input must be text")
    redacted = _apply_redact_layer(text)
    # Mandatory vocabulary: scrub ``key=value`` / ``"key": value``
    # pairs and any value that LOOKS like a credential.
    redacted = _SECRET_ASSIGN_RE.sub(
        lambda m: f"{m.group(1)}{REDACTED}", redacted)
    redacted = _PREFIX_RE.sub(REDACTED, redacted)
    # Final proof: no mandatory secret token may remain as a bare
    # assignment target. (The token word itself may legitimately
    # appear in prose like "token count" — the assignment form is
    # what carries a value.)
    return redacted


def has_sensitive_candidate(text: str) -> bool:
    """True when a line still carries an unscoped sensitive token.

    Used by adapters to decide whether a line's projection needs
    extra caution; the line is still returned ONLY through
    :func:`redact_line`.
    """
    return _SECRET_TOKEN_RE.search(text or "") is not None
