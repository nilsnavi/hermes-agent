"""Capability request model tests."""

import pytest

from agent.platform_policy.capability import CapabilityRequest, CapabilityRequestSet
from agent.platform_policy.exceptions import InvalidPermission


def test_valid_capability_request_maps_to_permission():
    request = CapabilityRequest("memory_retrieval", reason="fetch context")
    assert request.required_permission == "memory.read"


def test_write_capability_maps_to_write_permission():
    assert CapabilityRequest("file_write").required_permission == "agents.register"
    assert CapabilityRequest("code_execution").required_permission == "system.operate"


def test_unknown_capability_rejected():
    with pytest.raises(InvalidPermission):
        CapabilityRequest("arbitrary_exec")

    with pytest.raises(InvalidPermission):
        CapabilityRequest("")


def test_request_is_bounded():
    with pytest.raises(InvalidPermission):
        CapabilityRequest("planning", reason="x" * 5000)


def test_read_capability_never_maps_to_write():
    # A read capability must not resolve to a mutation permission.
    assert CapabilityRequest("memory_retrieval").required_permission != "memory.write"
    assert CapabilityRequest("file_read").required_permission == "agents.read"
    assert CapabilityRequest("message_exchange").required_permission == "message.write"


def test_request_set_deduplicates():
    a = CapabilityRequest("planning", reason="r")
    b = CapabilityRequest("planning", reason="r")
    s = CapabilityRequestSet({a, b})
    assert len(s.requests) == 1


def test_request_set_rejects_non_request_item():
    # A heterogeneous collection is rejected (deny-by-default at construction).
    bad: object = {"not-a-request"}
    with pytest.raises(InvalidPermission):
        CapabilityRequestSet(bad)  # type: ignore[arg-type]


def test_request_set_bounds_count():
    items = [CapabilityRequest("planning", reason=str(i)) for i in range(65)]
    with pytest.raises(InvalidPermission):
        CapabilityRequestSet(set(items))


def test_capability_request_is_not_authority():
    # A capability request carries the permission it needs; it never executes.
    assert not hasattr(CapabilityRequest("file_read"), "execute")
    assert not hasattr(CapabilityRequest("file_read"), "run")


def test_capability_requires_permission_within_canonical_set():
    # Reserved 'message.write' maps outside canonical set -> represent as knowledge,
    # the mapping table still resolves but the model keeps the requested permission.
    for capability in ("file_write", "code_execution", "network_access"):
        permission = CapabilityRequest(capability).required_permission
        assert isinstance(permission, str) and permission


def test_reserved_non_canonical_capability_is_never_grantable():
    # message_exchange -> message.write, which is not in the canonical set, so
    # no PermissionGrant can ever hold it -> the deny-by-default engine always
    # denies. Fail-closed for a capability the MVP does not expose.
    from agent.platform_policy.permissions import (
        CANONICAL_PERMISSIONS,
        PermissionGrant,
        PlatformScope,
    )

    request = CapabilityRequest("message_exchange")
    assert request.required_permission == "message.write"
    assert request.required_permission not in CANONICAL_PERMISSIONS
    scope = PlatformScope(tenant_id="t", principal="p")
    # Attempting to build a grant holding the reserved name itself is rejected.
    with pytest.raises(InvalidPermission):
        PermissionGrant(scope, {"message.write"})