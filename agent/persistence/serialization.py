"""Serialization helpers (Sprint 1.0.3).

Reuses the models' existing ``to_dict``/``from_dict`` — no second layer.
Datetimes are ISO-8601 UTC strings; enums store their ``.value``; None /
empty containers roundtrip via JSON.
"""

import json
from datetime import datetime
from typing import Any, Optional


def dumps(value: Any) -> str:
    """Canonical JSON for storage columns (sorted keys, unicode kept)."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def loads(raw: Optional[str]) -> Any:
    if raw is None or raw == "":
        return None
    return json.loads(raw)


def parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def isoformat(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None
