"""Sprint 1.3.9 — static service registry (authority = static)."""
from __future__ import annotations

from .models import (BlastRadius, ConfigValidator, Criticality, HealthContract,
                    RiskClass, SelfControlClass, ServiceClass, ServiceProfile)

GATEWAY = ServiceProfile("hermes-gateway", 1, "hermes-gateway.service",
                         expected_executable="hermes",
                         expected_exec_start="/usr/local/bin/hermes",
                         service_class=ServiceClass.HERMES_CORE,
                         criticality=Criticality.CRITICAL,
                         self_control_class=SelfControlClass.SELF_CONTROL_FORBIDDEN,
                         reload_supported=True, restart_supported=True,
                         rollback_strategy="manual_operator",
                         health_contract_id="hc-gateway",
                         blast_radius_ceiling=BlastRadius.NONE)

AUX = ServiceProfile("hermes-aux-agent", 1, "hermes-aux-agent.service",
                     expected_executable="hermes-aux",
                     expected_exec_start="/usr/local/bin/hermes-aux",
                     expected_exec_reload="/usr/local/bin/hermes-aux reload",
                     service_class=ServiceClass.HERMES_AUXILIARY,
                     criticality=Criticality.LOW, reload_supported=True,
                     restart_supported=True, rollback_strategy="restore_config_and_reload",
                     risk_class=RiskClass.LOW, blast_radius_ceiling=BlastRadius.SERVICE,
                     health_contract_id="hc-aux", config_validator_id="cv-aux")

TEST = ServiceProfile("test-echo", 1, "test-echo.service",
                      expected_executable="test-echo",
                      expected_exec_start="/usr/local/bin/test-echo",
                      service_class=ServiceClass.HERMES_AUXILIARY,
                      criticality=Criticality.LOW, reload_supported=True,
                      restart_supported=True, rollback_strategy="restore_config_and_reload",
                      risk_class=RiskClass.LOW, blast_radius_ceiling=BlastRadius.SERVICE,
                      health_contract_id="hc-test", config_validator_id="cv-test")


def build_default_profiles() -> dict[str, ServiceProfile]:
    return {"hermes-gateway": GATEWAY, "hermes-aux-agent": AUX, "test-echo": TEST}


class ServiceRegistry:
    """Static registry. Profiles are the authoritative upper bound."""

    def __init__(self, profiles: dict[str, ServiceProfile] | None = None,
                 contracts: dict[str, HealthContract] | None = None,
                 validators: dict[str, ConfigValidator] | None = None) -> None:
        self.profiles = profiles if profiles is not None else build_default_profiles()
        self.contracts = contracts if contracts is not None else {
            "hc-gateway": HealthContract("hc-gateway", "hermes-gateway"),
            "hc-aux": HealthContract("hc-aux", "hermes-aux-agent"),
            "hc-test": HealthContract("hc-test", "test-echo"),
        }
        self.validators = validators if validators is not None else {
            "cv-aux": ConfigValidator("cv-aux", "hermes-aux-agent", kind="json_schema"),
            "cv-test": ConfigValidator("cv-test", "test-echo", kind="json_schema"),
        }

    def get(self, service_id: str) -> ServiceProfile | None:
        return self.profiles.get(service_id)

    def contract(self, contract_id: str) -> HealthContract | None:
        return self.contracts.get(contract_id)

    def validator(self, validator_id: str) -> ConfigValidator | None:
        return self.validators.get(validator_id)
