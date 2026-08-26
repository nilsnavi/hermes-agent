"""Worker configuration (Phase 8.3 §24, §14).

Defaults are the FROZEN SAFE defaults: worker disabled, kill switch ENGAGED,
zero sampling, network/memory/mutation all OFF.  Any unknown key, missing
required value, or out-of-bounds value -> FAIL CLOSED (config load refuses to
produce a partially configured worker).  Config is an opaque data value: it
never grants authority by itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .exceptions import WorkerConfigError

#: Frozen safe defaults (Phase 8.3 §24).
DEFAULT_CONFIG: dict[str, object] = {
    "worker_enabled": False,
    "shadow_kill_switch": True,       # ON
    "sampling_percent": 0,
    "sampling_mode": "off",           # off | sample | full_shadow
    "network_read_only": False,
    "memory_writes": False,
    "mutation_capabilities": False,
    "max_queue_depth": 1000,
    "max_envelope_bytes": 65536,
    "max_concurrent_runs": 16,
    "max_task_duration_ms": 5000,
    "max_agent_duration_ms": 4000,
    "max_dag_nodes": 64,
    "max_retry_count": 2,
}

_INT_BOUNDS: dict[str, tuple[int, int]] = {
    "sampling_percent": (0, 100),
    "max_queue_depth": (1, 100_000),
    "max_envelope_bytes": (256, 4 * 1024 * 1024),
    "max_concurrent_runs": (1, 512),
    "max_task_duration_ms": (100, 10 * 60 * 1000),
    "max_agent_duration_ms": (100, 10 * 60 * 1000),
    "max_dag_nodes": (1, 10_000),
    "max_retry_count": (0, 100),
}

_BOOL_KEYS = frozenset(
    {"worker_enabled", "shadow_kill_switch", "network_read_only",
     "memory_writes", "mutation_capabilities"}
)
_STR_MODE_KEYS = frozenset({"sampling_mode"})


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Immutable, validated worker configuration (fail-closed on any error)."""

    worker_enabled: bool = False
    shadow_kill_switch: bool = True
    sampling_percent: int = 0
    sampling_mode: str = "off"
    network_read_only: bool = False
    memory_writes: bool = False
    mutation_capabilities: bool = False
    max_queue_depth: int = 1000
    max_envelope_bytes: int = 65536
    max_concurrent_runs: int = 16
    max_task_duration_ms: int = 5000
    max_agent_duration_ms: int = 4000
    max_dag_nodes: int = 64
    max_retry_count: int = 2

    @classmethod
    def from_mapping(cls, raw: dict[str, object] | None) -> "WorkerConfig":
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise WorkerConfigError("config must be a mapping")
        unknown = set(raw) - set(DEFAULT_CONFIG)
        if unknown:
            raise WorkerConfigError(f"unknown config keys: {sorted(unknown)}")
        out: dict[str, object] = dict(DEFAULT_CONFIG)
        for k, v in raw.items():
            out[k] = _coerce(k, v)
        # Apply int bounds after coercion for both defaults and provided values.
        for k, (lo, hi) in _INT_BOUNDS.items():
            val = out[k]
            if not isinstance(val, int) or isinstance(val, bool) or not (lo <= val <= hi):
                raise WorkerConfigError(f"config {k} out of bounds [{lo}, {hi}]: {val!r}")
        try:
            return cls(**out)  # type: ignore[arg-type]
        except TypeError as exc:  # pragma: no cover - dataclass shape is stable
            raise WorkerConfigError(str(exc))

    # -- semantic accessors --------------------------------------------------

    @property
    def kill_switch_engaged(self) -> bool:
        return self.shadow_kill_switch

    @property
    def enabled(self) -> bool:
        return self.worker_enabled and not self.shadow_kill_switch

    def as_dict(self) -> dict[str, object]:
        return {
            "worker_enabled": self.worker_enabled,
            "shadow_kill_switch": self.shadow_kill_switch,
            "sampling_percent": self.sampling_percent,
            "sampling_mode": self.sampling_mode,
            "network_read_only": self.network_read_only,
            "memory_writes": self.memory_writes,
            "mutation_capabilities": self.mutation_capabilities,
            "max_queue_depth": self.max_queue_depth,
            "max_envelope_bytes": self.max_envelope_bytes,
            "max_concurrent_runs": self.max_concurrent_runs,
            "max_task_duration_ms": self.max_task_duration_ms,
            "max_agent_duration_ms": self.max_agent_duration_ms,
            "max_dag_nodes": self.max_dag_nodes,
            "max_retry_count": self.max_retry_count,
        }


def _coerce(key: str, value: object) -> object:
    if key in _BOOL_KEYS:
        if not isinstance(value, bool):
            raise WorkerConfigError(f"config {key} must be a bool, got {type(value).__name__}")
        return value
    if key in _STR_MODE_KEYS:
        if not isinstance(value, str) or value not in ("off", "sample", "full_shadow"):
            raise WorkerConfigError(f"config {key} must be a valid sampling_mode, got {value!r}")
        return value
    if key in ("sampling_percent", "max_queue_depth", "max_envelope_bytes",
               "max_concurrent_runs", "max_task_duration_ms", "max_agent_duration_ms",
               "max_dag_nodes", "max_retry_count"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise WorkerConfigError(f"config {key} must be an int, got {type(value).__name__}")
        return value
    if key in ("worker_enabled", "shadow_kill_switch", "network_read_only",
               "memory_writes", "mutation_capabilities"):
        if not isinstance(value, bool):
            raise WorkerConfigError(f"config {key} must be a bool")
        return value
    raise WorkerConfigError(f"unsupported config key {key!r}")


__all__ = ["DEFAULT_CONFIG", "WorkerConfig"]