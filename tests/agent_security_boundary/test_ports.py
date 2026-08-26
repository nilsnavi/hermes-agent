"""ports.py: mandatory pipeline seams + deterministic side-effect classification.

No port here performs execution. These tests assert the typed Protocol seams
(exactly five mandatory components) and that side-effect classification is a
pure, deterministic map (data, never a grant).
"""

import pytest

from agent.agent_security_boundary.ports import (
    MANDATORY_PORT_NAMES,
    CapabilityRouterSeam,
    PolicyEvaluator,
    SandboxAdapterSeam,
    SystemBoundarySeam,
    ToolExecutorSeam,
    side_effect_of_operation,
)
from agent.agent_security_boundary.status import SideEffectClass


def test_mandatory_port_names_are_exactly_five():
    assert MANDATORY_PORT_NAMES == (
        "policy",
        "capability_router",
        "system_boundary",
        "executor",
        "sandbox",
    )


def test_policy_evaluator_is_runtime_checkable():
    class _P(PolicyEvaluator):
        def evaluate(self, request):
            return None

    assert isinstance(_P(), PolicyEvaluator)


def test_capability_router_seam_is_runtime_checkable():
    class _R(CapabilityRouterSeam):
        def decide(self, request):
            return None

    assert isinstance(_R(), CapabilityRouterSeam)


def test_system_boundary_seam_exposes_all_methods():
    class _B(SystemBoundarySeam):
        def preflight(self, request):
            return None

        def authorize(self, request):
            return None

        def verify_before_execute(self, request):
            return None

        def verify_after_execute(self, request):
            return None

    b = _B()
    assert isinstance(b, SystemBoundarySeam)
    for method in (
        "preflight",
        "authorize",
        "verify_before_execute",
        "verify_after_execute",
    ):
        assert callable(getattr(b, method))


def test_tool_executor_seam_exposes_ready_and_execute():
    class _E(ToolExecutorSeam):
        def is_ready(self):
            return True

        def execute(self, request):
            return None

    assert isinstance(_E(), ToolExecutorSeam)


def test_sandbox_adapter_seam_is_runtime_checkable():
    class _A(SandboxAdapterSeam):
        def run(self, payload):
            return None

    assert isinstance(_A(), SandboxAdapterSeam)


# -- side-effect classification: pure deterministic map, no grant ------------

@pytest.mark.parametrize(
    "op,expected",
    [
        ("read_repository", SideEffectClass.READ_ONLY),
        ("inspect_files", SideEffectClass.READ_ONLY),
        ("analyze_code", SideEffectClass.READ_ONLY),
        ("search_index", SideEffectClass.READ_ONLY),
        ("list_agents", SideEffectClass.READ_ONLY),
        ("shell", SideEffectClass.EXECUTE),
        ("subprocess", SideEffectClass.EXECUTE),
        ("execute", SideEffectClass.EXECUTE),
        ("write_files", SideEffectClass.WRITE),
        ("write_file", SideEffectClass.WRITE),
        ("install_dependency", SideEffectClass.WRITE),
        ("git_commit", SideEffectClass.WRITE),
        ("git_push", SideEffectClass.WRITE),
        ("service_control", SideEffectClass.SERVICE_MUTATION),
        ("restart", SideEffectClass.SERVICE_MUTATION),
        ("execute_code", SideEffectClass.EXECUTE),
        ("run_shell", SideEffectClass.EXECUTE),
        ("system_control", SideEffectClass.SYSTEM_CONTROL),
        ("kernel", SideEffectClass.SYSTEM_CONTROL),
        ("network", SideEffectClass.NETWORK),
        ("http", SideEffectClass.NETWORK),
        ("fetch", SideEffectClass.NETWORK),
        ("totally_unknown_op", SideEffectClass.UNKNOWN),
    ],
)
def test_side_effect_of_operation_maps_deterministically(op, expected):
    assert side_effect_of_operation(op) is expected


def test_side_effect_of_operation_is_case_insensitive_and_stripped():
    assert side_effect_of_operation("  SHELL  ") is SideEffectClass.EXECUTE


def test_side_effect_of_operation_read_prefix_is_strict():
    # "write" is NOT a read_* prefix -> must not be misclassified as READ_ONLY.
    assert side_effect_of_operation("write") is SideEffectClass.WRITE
    assert side_effect_of_operation("write_files") is SideEffectClass.WRITE


def test_side_effect_of_operation_rejects_non_string():
    assert side_effect_of_operation(None) is SideEffectClass.UNKNOWN  # type: ignore[reportArgumentType]
    assert side_effect_of_operation(123) is SideEffectClass.UNKNOWN  # type: ignore[reportArgumentType]
    assert side_effect_of_operation("") is SideEffectClass.UNKNOWN