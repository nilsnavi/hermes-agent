"""SBL persistence (Sprint 1.3.3 §36).

~/.hermes/hermes-v2/sbl/: service_graph.json, graph.meta.json,
audit.jsonl, snapshots/. Requirements: atomic writes, schema_version,
generated_at, checksum, source/provenance, TTL, no secrets,
corruption detection. Production state.db schema is NOT touched.
"""

import hashlib
import json
import os
import tempfile
from typing import Any, Dict, Optional

#: SBL state directory (kept separate from production state.db §36)
SBL_DIR = os.path.expanduser("~/.hermes/hermes-v2/sbl")


def _atomic_write(path: str, payload: str) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".sbl-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _checksum(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def save_graph(graph: Any, dirpath: Optional[str] = None) -> str:
    """Persist a ServiceGraph with checksum + meta (atomic)."""
    base = dirpath or SBL_DIR
    g = graph.to_dict()
    payload = json.dumps(g, sort_keys=True, ensure_ascii=False)
    checksum = _checksum(payload)
    _atomic_write(os.path.join(base, "service_graph.json"), payload)
    meta = {
        "schema_version": 1,
        "generated_at": None,  # caller may set; kept minimal here
        "checksum": checksum,
        "source": "static/bounded",
        "ttl_s": 3600,
    }
    _atomic_write(os.path.join(base, "graph.meta.json"),
                  json.dumps(meta, sort_keys=True))
    return checksum


def load_graph(dirpath: Optional[str] = None) -> Any:
    """Load a ServiceGraph; corruption → CORRUPT health (detected)."""
    from .service_graph import ServiceGraph

    base = dirpath or SBL_DIR
    path = os.path.join(base, "service_graph.json")
    if not os.path.exists(path):
        return ServiceGraph(health="UNAVAILABLE")
    try:
        with open(path) as f:
            data = json.load(f)
        g = ServiceGraph.from_dict(data)
        return g
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return ServiceGraph(health="CORRUPT")


def append_audit(event: Dict[str, Any],
                 dirpath: Optional[str] = None) -> None:
    """Append one audit event (no secrets — caller sanitizes)."""
    base = dirpath or SBL_DIR
    os.makedirs(base, exist_ok=True)
    line = json.dumps(event, sort_keys=True, ensure_ascii=False,
                      default=str)
    with open(os.path.join(base, "audit.jsonl"), "a") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


__all__ = [
    "SBL_DIR",
    "save_graph",
    "load_graph",
    "append_audit",
]
