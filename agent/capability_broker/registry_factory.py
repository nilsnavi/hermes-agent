"""Trusted Phase 9.1.1 TestIT registry construction."""

from __future__ import annotations

from .context import TrustedSurface
from .registry import CapabilityDefinition, CapabilityRegistry


def build_testit_read_registry(
    *,
    required_secret_names: frozenset[str],
) -> CapabilityRegistry:
    """Build the exact three-operation read-only TestIT registry.

    Secret names are trusted deployment configuration. They are not taken
    from CapabilityOperationRequest or any LLM/user-controlled payload.
    """

    if not required_secret_names:
        raise ValueError("TestIT required secret names must not be empty")

    registry = CapabilityRegistry()

    common = dict(
        platform_capability="integration_read",
        allowed_surfaces=frozenset(
            {
                TrustedSurface.DESKTOP,
                TrustedSurface.WEBUI,
            }
        ),
        integration="testit",
        required_secrets=required_secret_names,
    )

    registry.register(
        CapabilityDefinition(
            operation="testit.projects.read",
            action="list_projects",
            **common,
        )
    )

    registry.register(
        CapabilityDefinition(
            operation="testit.testcases.read",
            action="list_testcases",
            **common,
        )
    )

    registry.register(
        CapabilityDefinition(
            operation="testit.testcase.read",
            action="get_testcase",
            **common,
        )
    )

    registry.freeze()
    return registry
