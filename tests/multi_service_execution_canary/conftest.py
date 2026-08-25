"""Shared fixtures using only the canary package public API."""
from __future__ import annotations

import dataclasses

import pytest

from agent.multi_service_execution_canary import (
    BASELINE_SHA,
    ENABLED,
    MODE,
    CanaryServiceRegistry,
    ProductionCanaryRequest,
)


@pytest.fixture
def exact_registry() -> CanaryServiceRegistry:
    return CanaryServiceRegistry()


@pytest.fixture
def exact_request():
    def make(**changes) -> ProductionCanaryRequest:
        request = ProductionCanaryRequest.for_exact_canary(
            request_id="request-1",
            baseline_sha=BASELINE_SHA,
            generation=1,
            approval_id="approval-1",
            plan_hash="plan-1",
            created_monotonic=10.0,
            expires_monotonic=1_000.0,
        )
        value = dataclasses.replace(request, **changes)
        if "approval_binding" not in changes:
            value = dataclasses.replace(value, approval_binding=value.expected_approval_binding())
        return value
    return make


@pytest.fixture
def green_gates() -> dict[str, bool]:
    return {
        "identity_valid": True,
        "graph_healthy": True,
        "approval_valid": True,
        "budget_available": True,
        "locks_available": True,
        "kill_switch_off": True,
        "system_control_off": True,
        "generic_service_control_denied": True,
        "real_adapter_disabled": True,
    }


@pytest.fixture
def canary_env() -> dict[str, str]:
    return {ENABLED: "true", MODE: "canary"}


@pytest.fixture
def fixed_clock():
    return lambda: 100.0
