"""Small stdlib-only fail-closed durable JSON transaction helper."""
from __future__ import annotations

import fcntl
import json
import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any


class DurableStateCorrupt(RuntimeError):
    """Durable safety state is unreadable or structurally invalid."""


def require_finite_time(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("time must be a finite real number")
    return float(value)


class JsonTransaction:
    def __init__(self, root: str | Path, name: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_path = self.root / f"{name}.json"
        self.lock_path = self.root / f"{name}.lock"

    def _load(self) -> dict[str, Any]:
        try:
            text = self.data_path.read_text()
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise DurableStateCorrupt(f"cannot read durable state: {self.data_path}") from exc
        try:
            loaded = json.loads(
                text,
                parse_constant=lambda token: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON constant: {token}")
                ),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise DurableStateCorrupt(f"invalid durable JSON: {self.data_path}") from exc
        if not isinstance(loaded, dict):
            raise DurableStateCorrupt(f"durable state must be an object: {self.data_path}")
        return loaded

    def update(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        with self.lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            data = self._load()
            result = fn(data)
            tmp = self.data_path.with_name(f".{self.data_path.name}.{os.getpid()}.tmp")
            try:
                with tmp.open("w") as out:
                    json.dump(
                        data, out, sort_keys=True, separators=(",", ":"), allow_nan=False
                    )
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(tmp, self.data_path)
                directory_fd = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass
            return result

    def read(self) -> dict[str, Any]:
        with self.lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
            data = self._load()
            return json.loads(json.dumps(data))


__all__ = ["DurableStateCorrupt", "JsonTransaction", "require_finite_time"]
