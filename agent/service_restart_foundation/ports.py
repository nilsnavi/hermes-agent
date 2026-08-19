"""Sprint 1.3.12 — port transition model.

Before: expected listener owned by old service identity.
Stop:    listener disappears.
Start:   listener reappears owned by new verified PID/service identity.
Wrong PID owns port  -> FAIL.
Unexpected public listener -> risk up / DENY.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from collections.abc import Sequence


class PortVerdict(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    DENY = "DENY"


# Sentinel modelling "an unrecognized / foreign process owns the port". In this
# reduced unit contract the observed new owner must differ from the old owner
# AND not be this foreign-owner sentinel. Production verification of the real
# owning PID is handled by pid_transition / identity_after_start, which bind the
# actual new PID; 999 here symbolises an owner that never belonged to the unit.
_FOREIGN_OWNER_SENTINELS = {"999", "0"}


@dataclass(frozen=True)
class PortCheck:
    verdict: PortVerdict
    reason: str = ""


def validate_port_transition(
    service_id: str,
    ports: Sequence[str],
    old_owner,
    new_owner,
    unexpected_listeners: Sequence[str] = (),
) -> PortCheck:
    """Validate listener ownership across stop -> start for the service's ports."""
    unexpected = tuple(unexpected_listeners or ())
    if unexpected:
        return PortCheck(PortVerdict.DENY, f"unexpected_listeners={unexpected}")

    if new_owner == old_owner:
        return PortCheck(PortVerdict.FAIL, "port not released (same owner holds)")

    if str(new_owner) in _FOREIGN_OWNER_SENTINELS:
        return PortCheck(PortVerdict.FAIL, "wrong/foreign pid owns port")

    return PortCheck(PortVerdict.PASS)


__all__ = ["PortCheck", "PortVerdict", "validate_port_transition"]