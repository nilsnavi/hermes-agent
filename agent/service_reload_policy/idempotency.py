"""Sprint 1.3.11 — durable idempotency (closes 1.3.10 T.D.)."""
from __future__ import annotations

import hashlib
import json
import os


def semantic_key(service, version, op, identity, config_hash, intent):
    h = hashlib.sha256()
    h.update(b"|".join(str(x).encode() for x in
             (service, version, op, identity, config_hash, intent)))
    return h.hexdigest()


class DurableIdempotency:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def _read(self):
        try:
            with open(self.path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)

    def lookup(self, key):
        return self._read().get(key)

    def record(self, key, result):
        d = self._read()
        d[key] = result
        self._write(d)