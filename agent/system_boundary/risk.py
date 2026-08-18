"""Risk model (Sprint 1.3.3 §6, §41).

Effective risk = max(intent, capability, tool, context, sbl_floor).
Invariant: risk_after >= risk_before — no SBL component may reduce
risk. The SBL only RAISES the floor; approval remains the Policy
Engine's decision.
"""

from typing import Dict, List

#: canonical risk ordering (higher index = higher risk)
RISK_ORDER: List[str] = [
    "NONE",
    "READ_ONLY",
    "LOW",
    "MEDIUM",
    "HIGH",
    "SERVICE",
    "SYSTEM",
    "CRITICAL",
]

_RISK_INDEX: Dict[str, int] = {
    level: i for i, level in enumerate(RISK_ORDER)
}


def risk_index(level: str) -> int:
    return _RISK_INDEX.get(str(level).upper(), _RISK_INDEX["CRITICAL"])


def apply_risk_floor(current: str, floor: str) -> str:
    """max(current, floor) — the SBL floor can only raise risk."""
    cur, flr = risk_index(current), risk_index(floor)
    return RISK_ORDER[cur] if cur >= flr else RISK_ORDER[flr]


def effective_risk(
    intent_risk: str = "READ_ONLY",
    capability_risk: str = "READ_ONLY",
    tool_risk: str = "READ_ONLY",
    context_risk: str = "READ_ONLY",
    sbl_risk_floor: str = "READ_ONLY",
) -> str:
    """§6 — effective risk is the max over all components."""
    levels = (intent_risk, capability_risk, tool_risk,
              context_risk, sbl_risk_floor)
    return max(levels, key=risk_index)


def risk_floor_for_operation(operation_class: str,
                             resource_class: str = "USER_DATA") -> str:
    """Conservative risk floor for an operation on a resource.

    System resources + mutation operations → SYSTEM floor minimum.
    Unknown operation or resource → CRITICAL (fail closed).
    """
    from .models import OperationClass, ResourceClass

    op = str(operation_class).upper()
    rc = str(resource_class).upper()
    if op == "READ":
        return "READ_ONLY"
    if rc in ("SECRET_RESOURCE", "UNKNOWN"):
        return "CRITICAL"
    if rc in ("SYSTEM_CONFIG", "SYSTEM_BINARY", "SYSTEM_SERVICE",
              "SYSTEM_STATE", "NETWORK_CONFIG", "PACKAGE_STATE",
              "PROCESS_RESOURCE", "CONTAINER_RESOURCE",
              "DEVICE_RESOURCE"):
        return "SYSTEM"
    if op in ("KERNEL_CONTROL", "FIREWALL_CHANGE", "MOUNT_CONTROL"):
        return "SYSTEM"
    if op in ("PACKAGE_INSTALL", "PACKAGE_REMOVE", "PACKAGE_UPGRADE",
              "CONTAINER_CONTROL", "NETWORK_CHANGE", "IDENTITY_CHANGE"):
        return "SYSTEM"
    return "MEDIUM"


__all__ = [
    "RISK_ORDER",
    "risk_index",
    "apply_risk_floor",
    "effective_risk",
    "risk_floor_for_operation",
]
