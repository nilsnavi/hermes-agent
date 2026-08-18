"""Durable append-only, redacted manual-review queue."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

_SECRET_PATTERNS = (
    r"api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}",
    r"password\s*[=:]\s*['\"][^'\"]+['\"]",
    r"password\s*[=:]\s*\S+",
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*",
    r"Authorization\s*:\s*(?:Basic|Bearer)\s+\S+",
    r"Authorization\s*:\s*[A-Za-z0-9\-._~+/]+=*",
    r"cookie\s*[=:]\s*['\"]?[A-Za-z0-9\-._~+/=]+",
    r"session[_-]?token\s*[=:]\s*\S+",
    r"token\s*[=:]\s*['\"]?[A-Za-z0-9\-._~+/]+",
    r"secret[_-]?(?:key|value)?\s*[=:]\s*['\"]?[^'\"\s]+",
)


def _redact_one(value: str) -> str:
    out = value
    for pat in _SECRET_PATTERNS:
        out = re.sub(pat, "[REDACTED]", out, flags=re.IGNORECASE)
    return out


def redact(value: object) -> object:
    if value is None:
        return None
    return _redact_one(str(value))


@dataclass(frozen=True)
class ManualReview:
    review_id: str
    transaction_id: str
    reason: str
    resource: str
    operation: str
    state_observed: Optional[str]
    state_expected: Optional[str]
    original_error: Optional[str]
    rollback_error: Optional[str]
    created_at: str
    status: str = "OPEN"

    def to_dict(self) -> dict:
        return asdict(self)


class ManualReviewStore:
    def __init__(self, sandbox_root) -> None:
        self._dir = os.path.join(sandbox_root.root, ".recovery")
        self._file = os.path.join(self._dir, "manual-reviews.jsonl")
        self._lock = threading.Lock()

    def create(self, *, transaction_id: str, reason: str, resource: str,
               operation: str, state_observed: object = None,
               state_expected: object = None, original_error: object = None,
               rollback_error: object = None) -> ManualReview:
        os.makedirs(self._dir, mode=0o700, exist_ok=True)
        item = ManualReview(
            review_id=str(uuid.uuid4()), transaction_id=str(transaction_id),
            reason=str(redact(reason)), resource=str(redact(resource)),
            operation=str(operation), state_observed=redact(state_observed),
            state_expected=redact(state_expected), original_error=redact(original_error),
            rollback_error=redact(rollback_error),
            created_at=datetime.now(timezone.utc).isoformat())
        line = json.dumps(item.to_dict(), sort_keys=True) + "\n"
        with self._lock:
            fd = os.open(self._file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line.encode("utf-8")); os.fsync(fd)
            finally:
                os.close(fd)
        return item

    def list(self, *, limit: int = 100) -> list[ManualReview]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        if not os.path.exists(self._file):
            return []
        rows = []
        with open(self._file, encoding="utf-8") as fh:
            for line in fh:
                try: rows.append(ManualReview(**json.loads(line)))
                except (ValueError, TypeError, json.JSONDecodeError): continue
        return sorted(rows, key=lambda x: (x.created_at, x.review_id))[:limit]

    def inspect(self, review_id: str) -> ManualReview:
        for item in self.list(limit=10000):
            if item.review_id == review_id:
                return item
        raise KeyError(review_id)
