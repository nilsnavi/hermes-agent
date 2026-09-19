"""Application provider router delegating route resolution to a port."""

from typing import Mapping

from hermes_core.domain.routing import RouteDecision, RoutePurpose
from hermes_core.ports.providers import ProviderPort


class ProviderRouter:
    def __init__(self, provider: ProviderPort) -> None:
        self._provider = provider

    def route(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        purpose: RoutePurpose = RoutePurpose.MAIN,
        options: Mapping[str, object] | None = None,
    ) -> RouteDecision:
        return self._provider.resolve(
            requested_provider=provider,
            requested_model=model,
            purpose=purpose,
            options=options,
        )
