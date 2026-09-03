"""Bridge from authenticated Platform identity to canonical platform policy."""

from __future__ import annotations

from typing import AbstractSet

from agent.platform_policy.capability import CapabilityRequest
from agent.platform_policy.exceptions import DeniedOperation
from agent.platform_policy.permissions import PermissionGrant, PlatformScope
from agent.platform_policy.policy import DenyByDefaultPolicy

from .context import TrustedCapabilityContext
from .errors import CapabilityDenied
from .registry import CapabilityDefinition


def scope_from_context(context: TrustedCapabilityContext) -> PlatformScope:
    principal = context.principal
    return PlatformScope(
        tenant_id=principal.tenant_id,
        principal=principal.principal_id,
        user_id=principal.user_id,
        is_system=principal.is_system,
    )


def require_capability(
    definition: CapabilityDefinition,
    context: TrustedCapabilityContext,
    *,
    grants: AbstractSet[PermissionGrant] = frozenset(),
) -> None:
    if context.surface not in definition.allowed_surfaces:
        raise CapabilityDenied("surface is not allowed")

    canonical_request = CapabilityRequest(
        definition.platform_capability,
        reason="capability broker operation",
        requested_resource=definition.integration,
        scope_ref=definition.operation,
    )

    scope = scope_from_context(context)

    try:
        DenyByDefaultPolicy.require(
            scope,
            canonical_request.required_permission,
            grants=frozenset(grants),
        )
    except DeniedOperation as exc:
        # Do not pass through the canonical exception text: it may contain
        # principal/scope details unnecessary at the broker response boundary.
        raise CapabilityDenied("canonical platform policy denied operation") from exc
