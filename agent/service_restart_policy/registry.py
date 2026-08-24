"""Static, immutable restart profile authority.

The canonical registry is defined once in this module and every
``RestartProfileRegistry`` instance snapshots it at construction time into an
isolated immutable view.  Authority reads (``resolve``/``entries``/
``service_ids``/``is_exact_profile``) always go through the instance snapshot so
that later module rebinding, monkeypatching, or global mutation of
``_CANONICAL_ENTRIES`` CANNOT change the authority of a runtime that already
exists.  Runtime discovery remains purely observational and never grants
authority.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType

from agent.service_restart_foundation.models import RestartProfile

MAX_REGISTERED_RESTART_SERVICES = 3
REGISTRY_VERSION = 1

_PROFILE = RestartProfile(
    service_id="hermes-aux-canary",
    profile_version=1,
    unit_name="hermes-aux-canary.service",
    service_class="HERMES_AUXILIARY",
    criticality="LOW",
    restart_supported=True,
    expected_stop_timeout=10.0,
    expected_start_timeout=10.0,
    expected_old_pid_behavior="MUST_EXIT",
    expected_new_pid_behavior="MUST_CHANGE",
    expected_executable="/usr/bin/python3",
    expected_user="hermes",
    risk_class="HIGH",
    blast_radius_ceiling="SERVICE",
)
# The underlying literal dict is only referenced by the MappingProxyType, so the
# mapping itself is immutable.  Module-level *rebinding* of this name is still
# possible in theory, which is why every registry instance snapshots it at init.
_CANONICAL_ENTRIES: Mapping[str, RestartProfile] = MappingProxyType(
    {_PROFILE.service_id: _PROFILE}
)


def _snapshot_digest(entries: Mapping[str, RestartProfile]) -> str:
    """Stable, canonical digest over the immutable entry snapshot."""
    payload = "\n".join(
        "{0}\0{1.profile_version}\0{1.unit_name}\0{1.service_class}".format(sid, prof)
        for sid, prof in sorted(entries.items())
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RestartProfileRegistry:
    """Code-defined authority sealed into an immutable per-instance snapshot.

    Runtime discovery may only provide drift evidence; it can never add a
    service to the authority surface.
    """

    __slots__ = ("_runtime_discovery", "_snapshot")
    MAX = MAX_REGISTERED_RESTART_SERVICES
    MAX_PROFILES = MAX
    # Compatibility view only; authority never reads this replaceable class attribute.
    _ENTRIES: Mapping[str, RestartProfile] = _CANONICAL_ENTRIES

    def __init__(self, runtime_discovery: Callable[[], Iterable[str]] | None = None) -> None:
        self._runtime_discovery = runtime_discovery
        # Snapshot at construction: a fresh, isolated, immutable view of the
        # code-defined source.  Later module rebinds cannot reach an existing
        # instance's authority set.
        self._snapshot: Mapping[str, RestartProfile] = MappingProxyType(
            dict(_CANONICAL_ENTRIES)
        )

    @property
    def registry_version(self) -> int:
        return REGISTRY_VERSION

    @property
    def registry_digest(self) -> str:
        return _snapshot_digest(self._snapshot)

    @property
    def entries(self) -> Mapping[str, RestartProfile]:
        return self._snapshot

    def service_ids(self) -> tuple[str, ...]:
        return tuple(self._snapshot)

    def resolve(
        self, service_id: str, profile_version: int | None = None
    ) -> RestartProfile | None:
        profile = self._snapshot.get(service_id)
        if profile is None or (
            profile_version is not None and profile.profile_version != profile_version
        ):
            return None
        return profile

    def is_exact_profile(self, profile: RestartProfile) -> bool:
        canonical = self._snapshot.get(profile.service_id)
        return canonical is not None and profile == canonical

    def observed_units(self) -> tuple[str, ...]:
        """Non-authoritative diagnostics only."""
        if self._runtime_discovery is None:
            return ()
        try:
            return tuple(self._runtime_discovery())
        except Exception:
            return ()


assert len(_CANONICAL_ENTRIES) <= RestartProfileRegistry.MAX_PROFILES
assert tuple(_CANONICAL_ENTRIES) == ("hermes-aux-canary",)

__all__ = ["MAX_REGISTERED_RESTART_SERVICES", "REGISTRY_VERSION", "RestartProfileRegistry"]
