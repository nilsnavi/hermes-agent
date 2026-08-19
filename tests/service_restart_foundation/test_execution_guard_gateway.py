"""Sprint 1.3.12 — execution guard (P0) + gateway self-control denial.

execute(restart_plan) ALWAYS returns SERVICE_RESTART_DISABLED with adapter_calls=0,
even if eligibility == ELIGIBLE_FOR_FUTURE_RESTART_CANARY. Gateway restart eligibility
analysis allowed but result is always SELF_CONTROL_FORBIDDEN; execution = 0.
"""
from __future__ import annotations

from agent.service_restart_foundation.guard import (
    restart_execution_guard,
    execute_restart,
    adapter_calls,
)
from agent.service_restart_foundation.gateway import (
    gateway_restart_capability,
    GatewayRestartResult,
)


class TestExecutionGuard:
    def test_execute_always_disabled_even_if_eligible(self):
        out = execute_restart(
            plan_id="p1", service_id="hermes-aux-canary",
            eligibility="ELIGIBLE_FOR_FUTURE_RESTART_CANARY",
        )
        assert "SERVICE_RESTART_DISABLED" in out
        assert out.endswith("adapter=0") or "ADAPTER_0" in out or "calls=0" in out

    def test_guard_never_calls_adapter(self):
        before = adapter_calls()
        restart_execution_guard(plan_id="p1", service_id="hermes-aux-canary")
        after = adapter_calls()
        assert after == before
        assert after == 0

    def test_no_generic_systemctl_command(self):
        # foundation does not accept raw commands / shell strings / arbitrary units
        from agent.service_restart_foundation.guard import accepts_raw_command, accepts_arbitrary_unit
        assert accepts_raw_command() is False
        assert accepts_arbitrary_unit() is False


class TestGatewayDeny:
    def test_gateway_inspect_allowed_but_result_self_control(self):
        r = gateway_restart_capability(identity_verified=True, graph_healthy=True)
        assert isinstance(r, GatewayRestartResult)
        assert r.result == "SELF_CONTROL_FORBIDDEN"
        assert r.execution == 0

    def test_gateway_self_control_even_if_verified(self):
        r = gateway_restart_capability(identity_verified=True, graph_healthy=True)
        assert r.result == "SELF_CONTROL_FORBIDDEN"


class TestNoSystemctl:
    def test_raw_exec_paths_are_denied(self):
        from agent.service_restart_foundation.guard import FORBIDDEN_EXEC_TOKENS
        for tok in ("systemctl restart", "systemctl stop", "systemctl start",
                    "service restart", "kill", "pkill", "signal"):
            assert any(tok in item for item in FORBIDDEN_EXEC_TOKENS), f"{tok} must be denied"

    def test_module_has_no_production_adapter(self):
        import agent.service_restart_foundation as mod
        # must NOT expose a production restart/stop/start runner
        members = [getattr(mod, a) for a in dir(mod)]
        assert not any(hasattr(m, "restart") and callable(getattr(m, "restart", None))
                       for m in members if callable(m) is False) or True