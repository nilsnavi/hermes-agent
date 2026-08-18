"""Sprint 1.3.8 — Limited Production Mutation Policy engine.

Decision layer (DENY / REQUIRE_APPROVAL / ...). Never grants generic authority.
Works only on registered Hermes-owned resource profiles + exact targets.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

from . import flags as flags_mod
from .budget import DurableBudget
from .exceptions import (ApprovalInvalid, BlastRadiusBlocked, BudgetExceeded,
                         CircuitBreakerOpen, ConsumerUnknownBlocked,
                         OperationNotAllowed, PolicyDenied, ProfileDisabled,
                         TargetNotRegistered)
from .models import (Operation, ProductionResourceProfile, TargetRegistration,
                     validate_target_name)
from .risk import BlastRadius, ConsumerClass, RiskClass, effective_risk

# ---- HARD DENY: system/service/etc. families stay blocked even when policy enabled
HARD_DENY_OPERATIONS = frozenset({
    "system_control", "system_write_any", "service_control", "service_restart",
    "service_reload", "process_signal", "package_change", "network_change",
    "firewall_change", "routing_change", "cron_change", "scheduler_change",
    "provider_change", "ssh_change", "user_change", "permission_change",
    "database_change", "docker_change", "systemd_change",
})

DENY_PATHS = frozenset({
    "~/.hermes/config.yaml", "~/.hermes/state.db", "~/.hermes/.env",
    "~/.ssh/*", "/etc/*", "/usr/*", "/var/lib/*", "/run/*",
    "/proc/*", "/sys/*", "/dev/*",
})

DENY_PREFIXES = ("/etc/", "/usr/", "/var/lib/", "/run/", "/proc/", "/sys/", "/dev/", "/root/")
HOMEDENY = ("config.yaml", "state.db", ".env")


def _expand(p: str) -> str:
    return os.path.expanduser(p)


def hard_denied_path(p: str) -> bool:
    """Absolute checks only (no glob/prefix grants); returns True if denied."""
    ap = os.path.abspath(p)
    home = _expand("~")
    for prefix in DENY_PREFIXES:
        if ap.startswith(prefix):
            return True
    base = os.path.basename(ap)
    if base in HOMEDENY and ap.startswith(os.path.join(home, ".hermes")):
        # config.yaml / state.db / .env anywhere under ~/.hermes
        return base in ("config.yaml", "state.db", ".env")
    if ".ssh" in ap.split(os.sep):
        return True
    return False


def hard_denied_operation(op: str) -> bool:
    return op.lower() in HARD_DENY_OPERATIONS


# ---- static profiles -------------------------------------------------------
def build_profiles() -> dict[str, ProductionResourceProfile]:
    m_dir = _expand("~/.hermes/managed/resources/markers/")
    j_dir = _expand("~/.hermes/managed/resources/json/")
    t_dir = _expand("~/.hermes/managed/resources/text/")
    return {
        "P1-MARKER": ProductionResourceProfile(
            profile_id="P1-MARKER", version=1, resource_class="marker",
            capability="HERMES_MANAGED_MARKER",
            allowed_operations=frozenset({Operation.SET_MARKER}),
            risk_class=RiskClass.LOW_MUTATION, consumer_class=ConsumerClass.NO_RUNTIME_CONSUMER,
            blast_radius_ceiling=BlastRadius.RESOURCE_ONLY, exact_target_dir=m_dir,
            owner="hermes", mode=0o600, max_payload_size=256, enabled=False,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z")),
        "P2-JSON": ProductionResourceProfile(
            profile_id="P2-JSON", version=1, resource_class="json",
            capability="HERMES_MANAGED_JSON",
            allowed_operations=frozenset({Operation.UPDATE_JSON}),
            risk_class=RiskClass.LOW_MUTATION, consumer_class=ConsumerClass.NO_RUNTIME_CONSUMER,
            blast_radius_ceiling=BlastRadius.RESOURCE_ONLY, exact_target_dir=j_dir,
            owner="hermes", mode=0o600, max_payload_size=16 * 1024, enabled=False,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z")),
        "P3-TEXT": ProductionResourceProfile(
            profile_id="P3-TEXT", version=1, resource_class="text",
            capability="HERMES_MANAGED_TEXT",
            allowed_operations=frozenset({Operation.REPLACE_TEXT}),
            risk_class=RiskClass.LOW_MUTATION, consumer_class=ConsumerClass.NO_RUNTIME_CONSUMER,
            blast_radius_ceiling=BlastRadius.RESOURCE_ONLY, exact_target_dir=t_dir,
            owner="hermes", mode=0o600, max_payload_size=16 * 1024, enabled=False,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z")),
    }


# ---- registries ------------------------------------------------------------
class PolicyEngine:
    """Static profiles + target registry + decision + execution hooks."""

    def __init__(self, *, profiles: dict | None = None,
                 budget: DurableBudget | None = None,
                 target_store_dir: str | None = None,
                 env=None) -> None:
        self.env = env
        self.profiles: dict[str, ProductionResourceProfile] = profiles or build_profiles()
        # target registry with bounded per-profile keys
        self.targets: dict[str, dict[str, TargetRegistration]] = {
            pid: {} for pid in self.profiles}
        self._target_store = target_store_dir
        self._budget = budget or DurableBudget(
            os.path.join(target_store_dir, "budget.json") if target_store_dir else None)

    # --- target registration (exact identity, boundary-checked) ---
    def register_target(self, profile_id: str, name: str, *, create_dir: bool = False) -> TargetRegistration:
        prof = self.profiles.get(profile_id)
        if prof is None:
            raise TargetNotRegistered(f"unknown profile {profile_id}")
        validate_target_name(name)
        base = _expand(prof.exact_target_dir)
        resolved = os.path.join(base, name + ".json")
        ap = os.path.abspath(resolved)
        # realpath-boundary check: resolved target must stay inside profile dir
        real_base = os.path.realpath(base)
        if os.path.commonpath([real_base, os.path.realpath(os.path.dirname(ap))]) != real_base:
            raise ValueError("resolved target escapes profile directory")
        if hard_denied_path(ap):
            raise ValueError("target path is hard-denied")
        if create_dir and not os.path.isdir(base):
            os.makedirs(base, exist_ok=True)
            os.chmod(base, 0o700)
        reg = TargetRegistration(
            profile_id=profile_id, target_id=name, resolved_path=ap,
            realpath=os.path.realpath(ap), owner="hermes", mode=0o600,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        self.targets[profile_id][name] = reg
        return reg

    def lookup_target(self, profile_id: str, name: str) -> TargetRegistration | None:
        return self.targets.get(profile_id, {}).get(name)

    # --- decision ---
    def evaluate(self, *, profile_id: str, target: str, operation: str,
                 payload_hash: str, approval: dict | None, global_success_max: int = 10,
                 resource_mode: str | None = None) -> dict:
        """Returns allow/deny decision dict. Raises on hard failures."""
        prof = self.profiles.get(profile_id)
        if prof is None or not prof.enabled:
            raise ProfileDisabled(profile_id)
        op = operation.lower()
        if hard_denied_operation(op):
            raise OperationNotAllowed(f"hard-denied operation {op}")
        if op not in {o.value for o in prof.allowed_operations}:
            raise OperationNotAllowed(f"{op} not allowed for {profile_id}")
        tgt = self.lookup_target(profile_id, target)
        if tgt is None or not tgt.enabled:
            raise TargetNotRegistered(target)
        # exact realpath identity
        if os.path.realpath(tgt.resolved_path) != tgt.realpath:
            raise PolicyDenied("target realpath mismatch (symlink?)")
        if hard_denied_path(tgt.resolved_path):
            raise PolicyDenied("target path hard-denied")
        mode = get_effective_mode(resource_mode, self.env)
        if mode != "limited":
            return {"allowed": False, "reason": "not in limited mode", "adapter_calls": 0}
        # consumer (specific cause) BEFORE risk elevation
        if prof.consumer_class in (ConsumerClass.ACTIVE_CONSUMER, ConsumerClass.UNKNOWN):
            raise ConsumerUnknownBlocked("active/unknown consumer")
        # risk / blast
        eff_risk = effective_risk(prof.risk_class, prof.consumer_class)
        if eff_risk.rank > RiskClass.MEDIUM_MUTATION.rank:
            raise PolicyDenied("risk too high")
        if prof.blast_radius_ceiling is not BlastRadius.RESOURCE_ONLY:
            raise BlastRadiusBlocked("blast radius > RESOURCE_ONLY")
        # circuit breaker
        if self._budget.circuit_open(profile_id):
            raise CircuitBreakerOpen(profile_id)
        # budget
        ok, why = self._budget.can_attempt(profile_id, prof.budget, global_success_max)
        if not ok:
            raise BudgetExceeded(why)
        # approval (profile-bound)
        if prof.approval_required:
            if not approval:
                return {"allowed": False, "reason": "approval required", "adapter_calls": 0}
            if approval.get("profile") != profile_id or approval.get("profile_version") != prof.version:
                raise ApprovalInvalid("approval not bound to this profile version")
            if approval.get("operation") != op:
                raise ApprovalInvalid("approval not bound to this operation")
            if approval.get("target") != target:
                raise ApprovalInvalid("approval not bound to this target")
            if approval.get("payload_hash") != payload_hash:
                raise ApprovalInvalid("approval payload mismatch")
            if approval.get("expires_ts", 0) < time.time():
                raise ApprovalInvalid("approval TTL expired")
        return {"allowed": True, "adapter_calls": 0, "profile": profile_id,
                "operation": op, "target": target}


def profile_enabled_guard(profile_id: str, env) -> bool:
    key = flags_mod.PER_PROFILE.get(
        {"P1-MARKER": "marker", "P2-JSON": "json", "P3-TEXT": "text"}.get(profile_id, ""))
    if not key:
        return False
    e = os.environ if env is None else env
    return (e.get(key) or "false").strip().lower() in ("1", "true", "yes")


def get_effective_mode(resource_mode: str | None, env) -> str:
    if resource_mode:
        return resource_mode
    return flags_mod.limited_active(env) and "limited" or "off"
