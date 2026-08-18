"""Sprint 1.3.8 — enums & helpers: risk, blast radius, consumer class."""
from __future__ import annotations

from enum import Enum, auto


class RiskClass(str, Enum):
    READ_ONLY = "read_only"
    LOW_MUTATION = "low_mutation"
    MEDIUM_MUTATION = "medium_mutation"
    HIGH_MUTATION = "high_mutation"

    @property
    def rank(self) -> int:
        return {"read_only": 0, "low_mutation": 1, "medium_mutation": 2,
                "high_mutation": 3}[self.value]

    def __le__(self, other):
        return self.rank <= RiskClass(other).rank


class BlastRadius(str, Enum):
    RESOURCE_ONLY = "resource_only"      # the ONLY permitted ceiling in 1.3.8
    SERVICE = "service"
    MULTI_SERVICE = "multi_service"
    HOST = "host"
    NETWORK = "network"
    UNKNOWN = "unknown"

    @property
    def rank(self) -> int:
        return {"resource_only": 0, "service": 1, "multi_service": 2,
                "host": 3, "network": 4, "unknown": 5}[self.value]

    def __le__(self, other):
        return self.rank <= BlastRadius(other).rank


class ConsumerClass(str, Enum):
    NO_RUNTIME_CONSUMER = "no_runtime_consumer"  # only class mutable in 1.3.8
    PASSIVE_READ_CONSUMER = "passive_read_consumer"
    ACTIVE_CONSUMER = "active_consumer"
    UNKNOWN = "unknown"


#: monotonic: profile risk can only be raised, never lowered, by the policy.
def effective_risk(declared: RiskClass, consumer: ConsumerClass) -> RiskClass:
    base = RiskClass(declared)
    if consumer in (ConsumerClass.ACTIVE_CONSUMER, ConsumerClass.UNKNOWN):
        return RiskClass.HIGH_MUTATION  # uncertain consumer -> raise
    if consumer == ConsumerClass.PASSIVE_READ_CONSUMER:
        return max(base, RiskClass.MEDIUM_MUTATION)
    return base
