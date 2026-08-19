"""Sprint 1.3.11 — enums + immutable ReloadServiceProfile + LimitedReloadPlan."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Class(str, Enum):
    AUXILIARY = "HERMES_AUXILIARY"
    CORE = "HERMES_CORE"
    DATASTORE = "DATASTORE"
    SCHEDULER = "SCHEDULER"
    PROVIDER = "PROVIDER"
    NETWORK = "NETWORK"
    SECURITY = "SECURITY"
    EXTERNAL = "EXTERNAL"
    UNKNOWN = "UNKNOWN"


class Criticality(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Consumer(str, Enum):
    NONE = "NO_RUNTIME_CONSUMER"
    PASSIVE = "PASSIVE_NONCRITICAL"
    ACTIVE_NC = "ACTIVE_NONCRITICAL"
    ACTIVE = "ACTIVE_CRITICAL"
    UNKNOWN = "UNKNOWN"


class Blast(str, Enum):
    NONE = "NONE"
    SERVICE = "SERVICE"
    MULTI = "MULTI_SERVICE"
    HOST = "HOST"
    NETWORK = "NETWORK"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class Op(str, Enum):
    RELOAD = "RELOAD"
    RESTART = "RESTART"
    STOP = "STOP"
    START = "START"


OUTCOME = {"COMMITTED", "FAILED", "UNKNOWN_OUTCOME"}