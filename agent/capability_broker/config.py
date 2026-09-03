"""Capability Broker feature gates.

No environment reading is performed here. Production wiring of environment
variables belongs to a later phase. Phase 9.1.1 constructs this immutable
configuration explicitly; defaults remain fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapabilityBrokerConfig:
    enabled: bool = False
    testit_enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be a bool")
        if type(self.testit_enabled) is not bool:
            raise TypeError("testit_enabled must be a bool")
