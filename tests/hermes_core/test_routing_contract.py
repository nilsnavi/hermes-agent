"""Executable C4 contracts for isolated hermes_core provider routing."""

from dataclasses import FrozenInstanceError

import pytest

from hermes_core.application.provider_router import ProviderRouter
from hermes_core.domain.routing import RouteDecision, RoutePurpose


class RecordingProvider:
    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision
        self.calls: list[dict[str, object]] = []

    def resolve(self, **kwargs: object) -> RouteDecision:
        self.calls.append(kwargs)
        return self.decision


def make_decision() -> RouteDecision:
    return RouteDecision(
        provider="provider-a",
        model="model-a",
        endpoint="https://example.invalid/v1",
        api_mode="chat_completion",
        credential_reference="profile-a/provider-a/key-slot-1",
        route_purpose=RoutePurpose.MAIN,
    )


def test_route_purpose_contains_current_supported_values() -> None:
    assert RoutePurpose.MAIN.value == "main"
    assert RoutePurpose.COMPRESSION.value == "compression"
    assert RoutePurpose.VISION.value == "vision"
    assert RoutePurpose.TITLE.value == "title"
    assert RoutePurpose.SEARCH.value == "search"


def test_route_decision_constructs_with_opaque_credential_reference() -> None:
    decision = make_decision()

    assert decision.provider == "provider-a"
    assert decision.model == "model-a"
    assert decision.endpoint == "https://example.invalid/v1"
    assert decision.api_mode == "chat_completion"
    assert decision.credential_reference == "profile-a/provider-a/key-slot-1"
    assert decision.route_purpose is RoutePurpose.MAIN
    assert "secret" not in decision.credential_reference


def test_route_decision_is_immutable() -> None:
    decision = make_decision()

    with pytest.raises(FrozenInstanceError):
        decision.provider = "provider-b"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        decision.route_purpose = RoutePurpose.VISION  # type: ignore[misc]


def test_provider_router_delegates_all_route_inputs_and_returns_provider_result() -> None:
    decision = make_decision()
    provider = RecordingProvider(decision)
    options = {"reasoning_effort": "low"}

    result = ProviderRouter(provider).route(
        provider="provider-a",
        model="model-a",
        purpose=RoutePurpose.COMPRESSION,
        options=options,
    )

    assert result is decision
    assert provider.calls == [
        {
            "requested_provider": "provider-a",
            "requested_model": "model-a",
            "purpose": RoutePurpose.COMPRESSION,
            "options": options,
        }
    ]

