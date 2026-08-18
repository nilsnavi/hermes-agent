"""Service boundary (Sprint 1.3.3 §29).

systemctl status → READ; systemctl restart → SERVICE_RESTART with the
target service; unknown service mutation → BLOCK. Service mutation
cannot hide behind a shell wrapper — the effective-action classifier
unwraps bash/sh/python/nohup before this boundary runs.
"""

from dataclasses import dataclass
from typing import List, Optional

from .models import (
    OperationClass,
    block_decision,
    pass_decision,
)


@dataclass(frozen=True)
class ServiceTarget:
    name: str
    operation: str
    is_read: bool = False


def classify_service_action(
    command_tokens: List[str],
) -> Optional[ServiceTarget]:
    """Classify a systemctl/service command line.

    Returns None when the command is not a service control command
    (caller decides), or a ServiceTarget otherwise.
    """
    if not command_tokens:
        return None
    head = command_tokens[0]
    if head not in ("systemctl", "service"):
        return None
    rest = command_tokens[1:]
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 1
    if i >= len(rest):
        return None
    verb = rest[i]
    if head == "systemctl" and verb in ("status", "show", "cat",
                                        "list-units", "is-active",
                                        "is-enabled", "help"):
        return ServiceTarget(name="", operation="READ", is_read=True)
    if head == "service" and verb in ("status", "--status-all"):
        return ServiceTarget(name="", operation="READ", is_read=True)
    op_map = {"restart": "SERVICE_RESTART", "stop": "SERVICE_STOP",
              "start": "SERVICE_START", "reload": "SERVICE_RESTART",
              "kill": "PROCESS_KILL", "enable": "SERVICE_ENABLE",
              "disable": "SERVICE_DISABLE"}
    op = op_map.get(verb)
    if op is None:
        # service NAME ACTION form
        if len(rest) >= 2:
            op = op_map.get(rest[1])
            if op is not None:
                return ServiceTarget(name=rest[0], operation=op)
        return ServiceTarget(name="", operation="UNKNOWN")
    target = rest[i + 1] if i + 1 < len(rest) else ""
    return ServiceTarget(name=target, operation=op)


class ServiceBoundary:
    """Fail-closed service boundary."""

    def evaluate(self, target: ServiceTarget,
                 known_services: Optional[set] = None) -> object:
        if target.is_read:
            return pass_decision("SBL_OK")
        if target.operation == "UNKNOWN":
            return block_decision("OPERATION_UNKNOWN",
                                  target_resources=[target.name])
        if target.name and known_services is not None \
                and target.name not in known_services:
            # unknown service mutation → BLOCK (§29)
            return block_decision("RESOURCE_UNKNOWN",
                                  target_resources=[target.name])
        return pass_decision("SBL_OK",
                             target_resources=[target.name] or [])


__all__ = ["ServiceTarget", "ServiceBoundary", "classify_service_action"]
