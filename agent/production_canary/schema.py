"""Sprint 1.3.7 §5 — strict schema-controlled canary content model.

Only exact allowed keys, exact types, no arbitrary/nested content,
no shell/paths/env/tokens/code. Size bound enforced separately.
"""
from __future__ import annotations

import json
from typing import Any

from .core import (CANARY_ALLOWED_KEYS, CANARY_SCHEMA_VERSION, MAX_CANARY_SIZE,
                   UPDATED_BY)

#: Content values that are never acceptable anywhere (defense in depth).
_FORBIDDEN_VALUE_MARKERS = (
    "http://", "https://", "{{", "}}", "`", "$(", ";", "&&", "|", ">",
    "bash", "sh ", "client_id", "client_secret", "password", "token=",
    "apikey", "api_key", "PRIVATE KEY", "Bearer ",
)


class SchemaError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def make_content(*, canary_id: str, generation: int, baseline_sha: str,
                 updated_at: str | None = None, schema_version: int = CANARY_SCHEMA_VERSION) -> bytes:
    """Build a schema-valid canary content as UTF-8 JSON bytes."""
    import time
    payload = {
        "schema_version": schema_version,
        "canary_id": canary_id,
        "generation": generation,
        "updated_at": updated_at or time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "updated_by": UPDATED_BY,
        "baseline_sha": baseline_sha,
    }
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def validate_canary_dict(data: Any) -> list[str]:
    """Return a list of schema violations (empty == valid)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["content is not a JSON object"]
    extras = set(data.keys()) - set(CANARY_ALLOWED_KEYS)
    if extras:
        errors.append(f"unexpected keys: {sorted(extras)}")
    if data.get("schema_version") != CANARY_SCHEMA_VERSION:
        errors.append(f"schema_version must be {CANARY_SCHEMA_VERSION}")
    for key in ("canary_id", "updated_by", "baseline_sha", "updated_at"):
        if key in data and not isinstance(data.get(key), str):
            errors.append(f"{key} must be a string")
    if "generation" in data and not isinstance(data.get("generation"), int):
        errors.append("generation must be an int")
    if "canary_id" in data and (not isinstance(data["canary_id"], str) or not data["canary_id"]):
        errors.append("canary_id required and non-empty")
    if "generation" in data and isinstance(data["generation"], int) and data["generation"] < 1:
        errors.append("generation must be >= 1")
    if "updated_by" in data and data.get("updated_by") != UPDATED_BY:
        errors.append(f"updated_by must be {UPDATED_BY}")
    # safety: scan all scalar string values for forbidden markers
    for k, v in data.items():
        if isinstance(v, str):
            low = v.lower()
            for marker in _FORBIDDEN_VALUE_MARKERS:
                if marker.lower() in low:
                    errors.append(f"forbidden marker in {k}")
                    break
    return errors


def validate_content_bytes(raw: bytes) -> list[str]:
    if len(raw) > MAX_CANARY_SIZE:
        return [f"size exceeds {MAX_CANARY_SIZE} bytes"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"not valid UTF-8: {exc}"]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]
    errors = validate_canary_dict(data)
    return errors


def make_canary(gen: int, canary_id: str, baseline_sha: str, updated_at: str) -> dict:
    """Construct a schema-valid canary dict (used by pipeline/shadow fixtures)."""
    return {
        "schema_version": CANARY_SCHEMA_VERSION,
        "canary_id": canary_id,
        "generation": gen,
        "updated_at": updated_at,
        "updated_by": UPDATED_BY,
        "baseline_sha": baseline_sha,
    }
