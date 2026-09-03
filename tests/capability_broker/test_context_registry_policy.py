import pytest

from agent.capability_broker.context import (
    TrustedCapabilityContext,
    TrustedSurface,
)
from agent.capability_broker.errors import (
    CapabilityDenied,
    InvalidTrustedContext,
    RegistryFrozen,
    UnknownCapability,
)
from agent.capability_broker.models import CapabilityOperationRequest
from agent.capability_broker.policy import require_capability, scope_from_context
from agent.capability_broker.registry import (
    CapabilityDefinition,
    CapabilityRegistry,
)
from agent.platform_api.auth import Principal
from agent.platform_policy.permissions import PermissionGrant


def principal() -> Principal:
    return Principal(
        tenant_id="tenant-1",
        principal_id="user-1",
        user_id="user-1",
        scopes={"integrations.read"},
    )


def context(surface=TrustedSurface.DESKTOP) -> TrustedCapabilityContext:
    return TrustedCapabilityContext(
        principal=principal(),
        surface=surface,
        request_id="req-1",
    )


def definition() -> CapabilityDefinition:
    return CapabilityDefinition(
        operation="testit.projects.read",
        platform_capability="integration_read",
        allowed_surfaces=frozenset(
            {TrustedSurface.DESKTOP, TrustedSurface.WEBUI}
        ),
        integration="testit",
        action="list_projects",
        required_secrets=frozenset(
            {"TESTIT_URL", "TESTIT_TOKEN"}
        ),
    )


def test_operation_request_carries_no_identity_authority():
    request = CapabilityOperationRequest(
        "testit.projects.read",
        {},
        "req-1",
    )
    assert not hasattr(request, "caller")
    assert not hasattr(request, "principal")
    assert not hasattr(request, "tenant")
    assert not hasattr(request, "permissions")
    assert not hasattr(request, "token")
    assert not hasattr(request, "url")
    assert not hasattr(request, "headers")
    assert not hasattr(request, "method")


def test_trusted_context_requires_exact_principal():
    with pytest.raises(InvalidTrustedContext):
        TrustedCapabilityContext(
            principal=object(),  # type: ignore[arg-type]
            surface=TrustedSurface.DESKTOP,
            request_id="req",
        )


def test_trusted_surface_is_closed_enum():
    with pytest.raises(InvalidTrustedContext):
        TrustedCapabilityContext(
            principal=principal(),
            surface="desktop",  # type: ignore[arg-type]
            request_id="req",
        )


def test_registry_requires_freeze_before_resolution():
    registry = CapabilityRegistry()
    registry.register(definition())
    with pytest.raises(Exception):
        registry.resolve("testit.projects.read")


def test_registry_freeze_is_immutable():
    registry = CapabilityRegistry()
    registry.register(definition())
    registry.freeze()

    assert registry.resolve("testit.projects.read") == definition()

    with pytest.raises(RegistryFrozen):
        registry.register(
            CapabilityDefinition(
                operation="testit.testcase.read",
                platform_capability="integration_read",
                allowed_surfaces=frozenset({TrustedSurface.DESKTOP}),
                integration="testit",
                action="get_testcase",
            )
        )


def test_unknown_operation_denied():
    registry = CapabilityRegistry()
    registry.register(definition())
    registry.freeze()
    with pytest.raises(UnknownCapability):
        registry.resolve("../../arbitrary_exec")


def test_policy_denies_without_exact_grant():
    with pytest.raises(CapabilityDenied):
        require_capability(definition(), context())


def test_policy_allows_exact_authenticated_scope_grant():
    ctx = context()
    scope = scope_from_context(ctx)
    grant = PermissionGrant(scope, {"integrations.read"})
    require_capability(
        definition(),
        ctx,
        grants=frozenset({grant}),
    )


def test_cross_tenant_grant_does_not_authorize():
    ctx = context()
    wrong_scope = type(scope_from_context(ctx))(
        tenant_id="tenant-2",
        principal="user-1",
        user_id="user-1",
    )
    grant = PermissionGrant(
        wrong_scope,
        {"integrations.read"},
    )

    with pytest.raises(CapabilityDenied):
        require_capability(
            definition(),
            ctx,
            grants=frozenset({grant}),
        )


def test_surface_restriction_is_authoritative():
    restricted = CapabilityDefinition(
        operation="testit.projects.read",
        platform_capability="integration_read",
        allowed_surfaces=frozenset({TrustedSurface.DESKTOP}),
        integration="testit",
        action="list_projects",
    )

    ctx = context(TrustedSurface.WEBUI)
    scope = scope_from_context(ctx)
    grant = PermissionGrant(scope, {"integrations.read"})

    with pytest.raises(CapabilityDenied):
        require_capability(
            restricted,
            ctx,
            grants=frozenset({grant}),
        )
