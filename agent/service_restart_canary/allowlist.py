"""Sprint 1.3.13 — single aux service restart canary (allowlist).

Static exact allowlist. Authority bound to service_id + unit_name + profile
version + expected executable + user + cgroup + restart contract version.
No glob / regex / prefix / env-only authority / runtime-discovered authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The single exact registered restart-canary service.
CANARY_SERVICE_ID = "hermes-aux-canary"
CANARY_UNIT = "hermes-aux-canary.service"
CANARY_RESTART_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class RestartAllowlistEntry:
    service_id: str
    unit_name: str
    profile_version: int = 1
    expected_executable: str = "/home/hermes/.hermes/managed/canary-service/handler.py"
    expected_user: str = "hermes"
    expected_cgroup: str = ""
    restart_contract_version: int = 1


# The static, exact, single-entry allowlist.
CANARY_ENTRY_EXEC = "/home/hermes/.hermes/managed/canary-service/handler.py"

CANARY_ENTRY = RestartAllowlistEntry(
    service_id=CANARY_SERVICE_ID,
    unit_name=CANARY_UNIT,
    profile_version=1,
    expected_executable=CANARY_ENTRY_EXEC,
    expected_user="hermes",
    expected_cgroup="",
    restart_contract_version=CANARY_RESTART_CONTRACT_VERSION,
)


class RestartAllowlist:
    """Exact-match allowlist with unicorn-fail-closed admission."""

    def __init__(self, entries: tuple[RestartAllowlistEntry, ...] = (CANARY_ENTRY,)) -> None:
        self._by_id: dict[str, RestartAllowlistEntry] = {e.service_id: e for e in entries}
        self._by_unit: dict[str, RestartAllowlistEntry] = {e.unit_name: e for e in entries}

    def contains_service(self, service_id: str) -> bool:
        return service_id in self._by_id

    def contains_unit(self, unit_name: str) -> bool:
        return unit_name in self._by_unit

    def entry_for_service(self, service_id: str) -> RestartAllowlistEntry | None:
        return self._by_id.get(service_id)

    def service_id_for_unit(self, unit_name: str) -> str | None:
        e = self._by_unit.get(unit_name)
        return e.service_id if e else None

    def exact(self) -> tuple[RestartAllowlistEntry, ...]:
        return tuple(self._by_id.values())


def default_allowlist() -> RestartAllowlist:
    return RestartAllowlist()


__all__ = [
    "CANARY_ENTRY",
    "CANARY_RESTART_CONTRACT_VERSION",
    "CANARY_SERVICE_ID",
    "CANARY_UNIT",
    "RestartAllowlist",
    "RestartAllowlistEntry",
    "default_allowlist",
]