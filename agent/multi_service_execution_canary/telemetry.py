"""Scalar-only canary telemetry; real counters cannot be incremented."""
from __future__ import annotations
import dataclasses
@dataclasses.dataclass(slots=True)
class CanaryTelemetry:
    canary_requests: int = 0
    canary_allowed: int = 0
    canary_denied: int = 0
    canary_simulated: int = 0
    canary_duplicates: int = 0
    canary_unknown: int = 0
    canary_recovery_required: int = 0
    simulated_child_calls: int = 0
    real_child_adapter_calls: int = 0
    simulated_compensation_calls: int = 0
    real_compensation_adapter_calls: int = 0
    authority_denials: int = 0
    kill_switch_denials: int = 0
    double_budget: int = 0
    double_approval: int = 0
