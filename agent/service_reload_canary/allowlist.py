"""Sprint 1.3.10 — exact single-service allowlist (static authority)."""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class RegisteredService:
    service_id: str
    unit_name: str
    manager: str
    scope: str
    expected_executable: str
    expected_user: str
    expected_exec_reload: str
    profile_version: int
    enabled: bool = True


class ServiceAllowlist:
    """One exact registered aux service. No glob/regex/env authority."""

    def __init__(self, services: list[RegisteredService] | None = None):
        self._reg: dict[str, RegisteredService] = {
            s.service_id: s for s in (services or [])
        }

    def register(self, s: RegisteredService) -> None:
        self._reg[s.service_id] = s

    def get(self, service_id: str) -> RegisteredService | None:
        return self._reg.get(service_id)

    def ids(self) -> list[str]:
        return list(self._reg)
