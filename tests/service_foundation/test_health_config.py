"""Sprint 1.3.9 — health contract, config validation, ports/process, CLI read-only."""
from __future__ import annotations

from agent.service_foundation import HealthStatus, ValidatorResult, evaluate_health, validate_config
from agent.service_foundation.models import ConfigValidator, HealthContract, Operation
from agent.service_foundation.registry import ServiceRegistry


def test_health_contract_eval():
    hc = HealthContract("hc", "x", checks=("systemd_active", "pid_alive"))
    assert evaluate_health(hc, {"systemd_active": HealthStatus.HEALTHY,
                                "pid_alive": HealthStatus.HEALTHY}) is HealthStatus.HEALTHY
    assert evaluate_health(hc, {"systemd_active": HealthStatus.HEALTHY,
                                "pid_alive": HealthStatus.UNHEALTHY}) is HealthStatus.UNHEALTHY
    assert evaluate_health(hc, {"systemd_active": HealthStatus.HEALTHY,
                                "pid_alive": HealthStatus.UNKNOWN}) is HealthStatus.UNKNOWN
    assert evaluate_health(None, {}) is HealthStatus.UNKNOWN


def test_health_contract_present_in_registry():
    r = ServiceRegistry()
    assert r.get("hermes-aux-agent").health_contract_id == "hc-aux"
    assert r.contract("hc-aux") is not None
    assert r.get("hermes-gateway").health_contract_id == "hc-gateway"


def test_config_validation_json():
    cv = ConfigValidator("cv", "x", kind="json_schema")
    assert validate_config(cv, b'{"a":1}') is ValidatorResult.VALID
    assert validate_config(cv, b'not json') is ValidatorResult.INVALID
    assert validate_config(None, b'{}') is ValidatorResult.UNAVAILABLE


def test_config_validator_present_in_registry():
    r = ServiceRegistry()
    assert r.get("hermes-aux-agent").config_validator_id == "cv-aux"
    assert r.validator("cv-aux") is not None


def test_ports_process_model_static():
    r = ServiceRegistry()
    # expected ports model is profile-static (no runtime discovery authority)
    assert hasattr(r.get("hermes-gateway"), "expected_executable")
    assert r.get("hermes-gateway").expected_executable == "hermes"
