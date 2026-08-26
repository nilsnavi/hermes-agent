"""coding.py: CodingAgent read-only / mutation hard-deny enforcement.

A declaration is never a grant. Even if an AgentDefinition or a channel
declares a forbidden capability, admission for that token is DENIED. The forbid
set is fixed and cannot be expanded by registration.
"""

import pytest

from agent.agent_security_boundary.coding import (
    CODING_FORBIDDEN_CAPABILITIES,
    CODING_READ_ONLY_CAPABILITIES,
    classify_side_effect,
    deny_disposition_for,
    is_forbidden_capability,
    is_read_only_capability,
)
from agent.agent_security_boundary.status import Disposition, SideEffectClass


def test_coding_read_only_set_is_exactly_four():
    assert CODING_READ_ONLY_CAPABILITIES == {
        "read_repository",
        "inspect_files",
        "analyze_code",
        "produce_patch_proposal",
    }


def test_coding_forbidden_set_covers_all_mutation_tokens():
    assert CODING_FORBIDDEN_CAPABILITIES == {
        "write_files",
        "execute_code",
        "install_dependency",
        "git_commit",
        "git_push",
        "run_shell",
        "service_control",
    }


@pytest.mark.parametrize(
    "cap",
    ["read_repository", "inspect_files", "analyze_code", "produce_patch_proposal"],
)
def test_read_only_capabilities_are_never_forbidden(cap):
    assert is_forbidden_capability(cap) is False
    assert is_read_only_capability(cap) is True


@pytest.mark.parametrize(
    "cap",
    [
        "write_files",
        "execute_code",
        "install_dependency",
        "git_commit",
        "git_push",
        "run_shell",
        "service_control",
    ],
)
def test_forbidden_capabilities_are_never_read_only(cap):
    assert is_forbidden_capability(cap) is True
    assert is_read_only_capability(cap) is False


def test_forbidden_set_is_fixed_and_cannot_be_expanded_by_registration():
    # The DENY set is a frozen constant; it cannot be grown from outside.
    import builtins

    with pytest.raises((TypeError, AttributeError)):
        CODING_FORBIDDEN_CAPABILITIES.add("anything")  # type: ignore[attr-defined]
    # Even an unknown never-seen token is not treated as admissible.
    assert is_forbidden_capability("totally_new_capability") is False
    assert is_read_only_capability("totally_new_capability") is False


def test_declared_but_not_granted_mutation_is_denied():
    # A declaration is metadata, not a grant: the deny set is authoritative even
    # if some AgentDefinition claimed write_files.
    assert is_forbidden_capability("write_files") is True
    assert deny_disposition_for("write_files") is Disposition.DENIED
    assert deny_disposition_for("execute_code") is Disposition.DENIED


def test_classify_side_effect_read_only():
    for cap in CODING_READ_ONLY_CAPABILITIES:
        assert classify_side_effect(cap) is SideEffectClass.READ_ONLY


def test_classify_side_effect_write():
    assert classify_side_effect("write_files") is SideEffectClass.WRITE
    assert classify_side_effect("install_dependency") is SideEffectClass.WRITE
    assert classify_side_effect("git_commit") is SideEffectClass.WRITE
    assert classify_side_effect("git_push") is SideEffectClass.WRITE


def test_classify_side_effect_execute():
    assert classify_side_effect("execute_code") is SideEffectClass.EXECUTE
    assert classify_side_effect("run_shell") is SideEffectClass.EXECUTE


def test_classify_side_effect_service_mutation():
    assert classify_side_effect("service_control") is SideEffectClass.SERVICE_MUTATION


def test_classify_side_effect_unknown():
    assert classify_side_effect("unknown_token") is SideEffectClass.UNKNOWN


def test_deny_disposition_is_fail_closed_for_unknown():
    # Unknown tokens are not admissible; they return ADMITTED only for routing,
    # but the gate independently routes UNKNOWN side-effect to HUMAN_REVIEW.
    assert deny_disposition_for("unknown_token") is not Disposition.DENIED