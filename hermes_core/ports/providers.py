"""Provider routing contract without SDK or credential access."""

from typing import Mapping, Protocol

from hermes_core.domain.routing import RouteDecision, RoutePurpose


class ProviderPort(Protocol):
    def resolve(
        self,
        *,
        requested_provider: str | None,
        requested_model: str | None,
        purpose: RoutePurpose,
        options: Mapping[str, object] | None = None,
    ) -> RouteDecision: ...
