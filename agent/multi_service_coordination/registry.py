"""Sprint 1.3.15 — coordination service set.

Sprint 1.3.15 does NOT expand the production restart registry (still size 1).
For shadow / rehearsal the coordinator reasons over three NON-authoritative
synthetic services:

    * existing hermes-aux-canary   (mirrors the real service identity)
    * fake-aux-a                   (sandbox-only fake)
    * fake-aux-b                   (sandbox-only fake)

These fake services are model objects only.  They are not discoverable as
production authority, they are not systemd production targets and they have no
host side effect.  The registry is immutable per-instance (authority reads go
through a construction-time snapshot).
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ServiceEntry:
    service_id: str
    profile_version: int
    service_class: str
    registered: bool
    self_control: bool = False
    forbidden: bool = False


def _entry(sid: str, version: int, cls: str, *, registered: bool = True) -> ServiceEntry:
    return ServiceEntry(sid, version, cls, registered=registered)


CANARY = _entry("hermes-aux-canary", 1, "HERMES_AUXILIARY")
FAKE_A = _entry("fake-aux-a", 1, "HERMES_AUXILIARY")
FAKE_B = _entry("fake-aux-b", 1, "HERMES_AUXILIARY")

_CANONICAL: Mapping[str, ServiceEntry] = MappingProxyType(
    {
        CANARY.service_id: CANARY,
        FAKE_A.service_id: FAKE_A,
        FAKE_B.service_id: FAKE_B,
    }
)

# Hard-denied mutation targets: gateway, scheduler, provider, database,
# network, auth, security, docker/container, ssh.
HARD_DENY_IDS = frozenset(
    {
        "hermes-gateway",
        "hermes",
        "gateway",
        "scheduler",
        "provider",
        "database",
        "postgres",
        "mongodb",
        "redis",
        "auth",
        "security",
        "docker",
        "container",
        "ssh",
        "hermes-aux-scheduler",
        "hermes-aux-provider",
    }
)


def _digest(entries: Mapping[str, ServiceEntry]) -> str:
    payload = "\n".join(
        "{0}\0{1.profile_version}\0{1.service_class}\0{1.registered}".format(sid, e)
        for sid, e in sorted(entries.items())
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CoordinationRegistry:
    MAX_SERVICES = 3
    MAX_DEPTH = 4
    MAX_EDGES = 16

    def __init__(
        self, runtime_discovery: Callable[[], Iterable[str]] | None = None
    ) -> None:
        self._discovery = runtime_discovery
        self._snapshot: Mapping[str, ServiceEntry] = MappingProxyType(
            dict(_CANONICAL)
        )

    @property
    def registry_digest(self) -> str:
        return _digest(self._snapshot)

    @property
    def entries(self) -> Mapping[str, ServiceEntry]:
        return self._snapshot

    def service_ids(self) -> tuple[str, ...]:
        return tuple(self._snapshot)

    def resolve(self, service_id: str) -> ServiceEntry | None:
        return self._snapshot.get(service_id)

    def is_known(self, service_id: str) -> bool:
        return service_id in self._snapshot

    def is_registered(self, service_id: str) -> bool:
        entry = self._snapshot.get(service_id)
        return entry is not None and entry.registered

    def is_self_control(self, service_id: str) -> bool:
        entry = self._snapshot.get(service_id)
        return bool(entry and entry.self_control) or service_id in {
            "hermes-gateway", "hermes", "gateway", "scheduler", "provider",
        }

    def is_hard_denied(self, service_id: str) -> bool:
        if service_id in HARD_DENY_IDS:
            return True
        entry = self._snapshot.get(service_id)
        return bool(entry and entry.forbidden)

    def observed_units(self) -> tuple[str, ...]:
        """Non-authoritative diagnostics only — never grants authority."""
        if self._discovery is None:
            return ()
        try:
            return tuple(self._discovery())
        except Exception:
            return ()


__all__ = [
    "CANARY",
    "FAKE_A",
    "FAKE_B",
    "CoordinationRegistry",
    "HARD_DENY_IDS",
    "ServiceEntry",
]