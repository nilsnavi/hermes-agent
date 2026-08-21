"""Sprint 1.3.13 — single aux service restart canary (durable idempotency).

Exactly-once restart. Key = service_id|profile_version|operation|old process
identity|config hash|transaction intent. Replay -> DUPLICATE, adapter=0.
File-backed so a subprocess restart re-reads the prior committed intent.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path


def idempotency_key(
    service_id: str,
    profile_version: int,
    operation: str,
    old_identity: str,
    config_hash: str,
    transaction_intent: str,
) -> str:
    raw = "|".join(
        [service_id, str(profile_version), operation, old_identity, config_hash, transaction_intent]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class DurableIdempotencyStore:
    """File-backed exactly-once store (Hermes-owned, additive, no state.db)."""

    def __init__(self, store_dir: str | Path) -> None:
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def prior(self, key: str) -> Mapping | None:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:
            return None

    def commit(self, key: str, outcome: str, started_at: float = 0.0) -> None:
        rec = {"key": key, "outcome": outcome, "started_at": started_at}
        tmp = self._path(key + ".tmp")
        tmp.write_text(json.dumps(rec))
        os.replace(tmp, self._path(key))

    def is_committed(self, key: str) -> bool:
        rec = self.prior(key)
        return bool(rec and rec.get("outcome") == "COMMITTED")


__all__ = ["DurableIdempotencyStore", "idempotency_key"]