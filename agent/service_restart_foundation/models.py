"""Sprint 1.3.12 — restart profile + process identity + transition models.

RESTART AUTHORITY IS SEPARATE FROM RELOAD AUTHORITY.
  - restart_authority_enabled is FORCED False in 1.3.12 regardless of input.
  - No raw exec fields (restart_command / stop_command / start_command) exist
    on the profile: there is no production restart adapter in this sprint.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# --------------------------------------------------------------------------- #
#  Enums
# --------------------------------------------------------------------------- #
class StopState(Enum):
    STOP_REQUESTED = "stop_requested"
    STOP_UNKNOWN = "stop_unknown"
    STOPPED = "stopped"


class StartState(Enum):
    START_REQUESTED = "start_requested"
    START_UNKNOWN = "start_unknown"
    STARTED = "started"
    STARTED_VERIFIED = "started_verified"


# --------------------------------------------------------------------------- #
#  Process identity — binds PID + process-start identity (not PID alone)
# --------------------------------------------------------------------------- #
class ProcessIdentity:
    """Immutable process identity: PID alone is NOT sufficient.

    PID reuse is detected via ``start_identity`` (boot-id / cgroup start token).
    """

    __slots__ = ("pid", "start_identity", "executable", "user", "cgroup", "unit")

    def __init__(
        self,
        pid: int,
        start_identity: str = "",
        executable: str = "",
        user: str = "",
        cgroup: str | None = None,
        unit: str | None = None,
        *,
        start: str | None = None,
    ) -> None:
        # ``start`` is a keyword-only alias for ``start_identity``.
        si = start_identity if start_identity else (start or "")
        object.__setattr__(self, "pid", pid)
        object.__setattr__(self, "start_identity", si)
        object.__setattr__(self, "executable", executable)
        object.__setattr__(self, "user", user)
        object.__setattr__(self, "cgroup", cgroup)
        object.__setattr__(self, "unit", unit)

    # -- make immutable -------------------------------------------------------
    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("ProcessIdentity is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ProcessIdentity is immutable")

    # -- equality / hash on pid + start_identity only -------------------------
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProcessIdentity):
            return NotImplemented
        return self.pid == other.pid and self.start_identity == other.start_identity

    def __hash__(self) -> int:
        return hash((self.pid, self.start_identity))

    def __repr__(self) -> str:
        return f"ProcessIdentity(pid={self.pid}, start={self.start_identity!r})"

    # -- business logic ------------------------------------------------------
    def same_process(self, other: "ProcessIdentity") -> bool:
        """True ONLY when pid AND start_identity are equal."""
        return self.pid == other.pid and self.start_identity == other.start_identity

    @property
    def start(self) -> str:
        """Alias for start_identity (read-only)."""
        return self.start_identity


# --------------------------------------------------------------------------- #
#  Restart transition — models old → new PID change
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RestartTransition:
    old: ProcessIdentity
    new: ProcessIdentity | None = None

    def new_pid_changed(self) -> bool:
        """True when the new PID differs from the old PID."""
        if self.new is None:
            return False
        return self.new.pid != self.old.pid


# --------------------------------------------------------------------------- #
#  RestartProfile — immutable, restart_authority_enabled forced False
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RestartProfile:
    service_id: str
    profile_version: int
    unit_name: str
    service_class: str
    criticality: str
    restart_supported: bool
    expected_stop_timeout: float
    expected_start_timeout: float
    expected_old_pid_behavior: str
    expected_new_pid_behavior: str
    expected_executable: str
    expected_user: str
    expected_ports: tuple = ()
    quiescence_policy: str = "REQUIRE_FULL_QUIESCENCE"
    startup_contract_id: str = "default"
    health_contract_id: str = "default"
    rollback_strategy: str = "RECONCILE_CURRENT_STATE"
    risk_class: str = "HIGH"
    blast_radius_ceiling: str = "SERVICE"
    restart_authority_enabled: bool = False

    def __post_init__(self) -> None:
        # P0: restart authority ALWAYS False in 1.3.12, regardless of input.
        object.__setattr__(self, "restart_authority_enabled", False)


__all__ = [
    "ProcessIdentity",
    "RestartProfile",
    "RestartTransition",
    "StartState",
    "StopState",
]