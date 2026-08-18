"""Sprint 1.3.7 §15/§16 — atomic write + idempotency (exactly-once)."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile


class AtomicWriteError(Exception):
    pass


def atomic_write(target: str, data: bytes, mode: int = 0o600,
                 owner_uid: int | None = None) -> None:
    """Write via temp file in same dir -> fsync -> chmod -> atomic rename -> fsync parent.

    Never truncates the existing target in place.
    """
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    if not os.path.isdir(parent):
        raise AtomicWriteError(f"parent not a dir: {parent}")
    fd, tmp = tempfile.mkstemp(prefix=".canary-", suffix=".tmp", dir=parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if owner_uid is not None:
            try:
                os.chown(tmp, owner_uid, -1)
            except PermissionError:
                pass
        os.rename(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    # fsync parent dir for durability of the rename
    try:
        dfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def idempotency_key(*, baseline_sha: str, transaction_id: str,
                    target_fingerprint: str, expected_after_hash: str) -> str:
    return hashlib.sha256("|".join(
        [baseline_sha, transaction_id, target_fingerprint, expected_after_hash]
    ).encode()).hexdigest()


class IdempotencyRegistry:
    """Durable registry of completed requests; duplicate key -> prior result.

    Persisted atomically to ``path`` so a fresh pipeline/process observes previous
    commits (exactly-once across runs, and crash-safe against double apply).
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._completed: dict[str, dict] = {}
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._completed = {k: v for k, v in data.items() if isinstance(v, dict)}
            except (OSError, ValueError):
                self._completed = {}

    def lookup(self, key: str) -> dict | None:
        return self._completed.get(key)

    def record(self, key: str, result: dict) -> None:
        self._completed[key] = result
        if self.path:
            tmp = f"{self.path}.tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._completed, f)
                    f.flush()
                    os.fsync(f.fileno())
                os.rename(tmp, self.path)
            except OSError:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
