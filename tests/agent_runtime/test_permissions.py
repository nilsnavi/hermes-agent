from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from agent.agent_runtime import AgentPermissions


PERMISSION_NAMES = (
    "read_files",
    "write_files",
    "execute_code",
    "network_access",
    "memory_read",
    "memory_write",
    "agent_message_send",
)


def test_permissions_are_immutable_and_default_deny_exact_surface() -> None:
    permissions = AgentPermissions()

    assert tuple(field.name for field in fields(permissions)) == PERMISSION_NAMES
    assert all(getattr(permissions, name) is False for name in PERMISSION_NAMES)
    with pytest.raises(FrozenInstanceError):
        permissions.read_files = True  # type: ignore[misc]


def test_permissions_accept_only_boolean_grants() -> None:
    permissions = AgentPermissions(read_files=True, network_access=True)

    assert permissions.read_files is True
    assert permissions.network_access is True
    with pytest.raises(ValueError):
        AgentPermissions(execute_code=1)  # type: ignore[arg-type]
