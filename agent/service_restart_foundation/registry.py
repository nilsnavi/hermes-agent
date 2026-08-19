"""Sprint 1.3.12 — restart service registry + service-class restriction.

Future restart candidate may ONLY be HERMES_AUXILIARY. Everything else is hard
denied (HERMES_CORE, gateway, scheduler, provider, database, network, security,
SSH, docker/container, auth, UNKNOWN, ...).
"""
from __future__ import annotations

from collections.abc import Mapping

from .models import RestartProfile

# Service classes that may never be a restart candidate in 1.3.12.
HARD_DENY_CLASSES = {
    "HERMES_CORE",
    "GATEWAY",
    "SCHEDULER",
    "PROVIDER",
    "DATABASE",
    "DATASTORE",
    "NETWORK",
    "SECURITY",
    "SSH",
    "DOCKER",
    "CONTAINER_RUNTIME",
    "AUTH",
    "UNKNOWN",
}

# Only this class is admitted as a future restart candidate.
ALLOWED_CLASS = "HERMES_AUXILIARY"


def class_allowed(service_class: str) -> bool:
    """Only HERMES_AUXILIARY services can ever be restart candidates."""
    return service_class == ALLOWED_CLASS


def class_deny_reason(service_class: str) -> str:
    if class_allowed(service_class):
        return ""
    return f"SERVICE_CLASS_DENIED({service_class})"


class RestartRegistry:
    """Registry of restart profiles for known auxiliary services (shadow)."""

    def __init__(self, profiles: Mapping[str, RestartProfile] | None = None) -> None:
        self._profiles: dict[str, RestartProfile] = dict(profiles or {})

    def register(self, profile: RestartProfile) -> None:
        if not class_allowed(profile.service_class):
            raise ValueError(
                f"service {profile.service_id} class {profile.service_class} "
                "is not a restart candidate (1.3.12: HERMES_AUXILIARY only)"
            )
        self._profiles[profile.service_id] = profile

    def get(self, service_id: str) -> RestartProfile | None:
        return self._profiles.get(service_id)

    def resolve(self, service_id: str) -> RestartProfile:
        p = self._profiles.get(service_id)
        if p is None:
            raise KeyError(f"no restart profile for {service_id}")
        return p

    def all(self) -> tuple[RestartProfile, ...]:
        # deterministic order
        return tuple(self._profiles[k] for k in sorted(self._profiles))


# Default registry with a reference aux canary profile (HERMES_AUXILIARY).
def default_aux_profile() -> RestartProfile:
    return RestartProfile(
        service_id="hermes-aux-canary",
        profile_version=1,
        unit_name="hermes-aux-canary.service",
        service_class="HERMES_AUXILIARY",
        criticality="LOW",
        restart_supported=True,
        expected_stop_timeout=10.0,
        expected_start_timeout=10.0,
        expected_old_pid_behavior="EXIT",
        expected_new_pid_behavior="NEW_PID_REQUIRED",
        expected_executable="/usr/bin/handler.py",
        expected_user="hermes",
        expected_ports=("127.0.0.1:8080",),
        quiescence_policy="REQUIRE_FULL_QUIESCENCE",
        startup_contract_id="default",
        health_contract_id="default",
        rollback_strategy="RECONCILE_CURRENT_STATE",
        risk_class="HIGH",
        blast_radius_ceiling="SERVICE",
        restart_authority_enabled=False,
    )


def default_registry() -> RestartRegistry:
    reg = RestartRegistry()
    reg.register(default_aux_profile())
    return reg


__all__ = [
    "ALLOWED_CLASS",
    "HARD_DENY_CLASSES",
    "RestartRegistry",
    "class_allowed",
    "class_deny_reason",
    "default_aux_profile",
    "default_registry",
]