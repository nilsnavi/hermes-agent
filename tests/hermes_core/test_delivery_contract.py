"""Executable C2 contracts for isolated hermes_core delivery behavior."""

from dataclasses import dataclass

import pytest

from hermes_core.application.delivery_service import DeliveryService
from hermes_core.domain.delivery import Delivery, DeliveryResult, DeliveryState


def make_delivery() -> Delivery:
    return Delivery(obligation_id="obligation-1", session_key="session-key", content="hello")


@dataclass
class RecordingTransport:
    result: DeliveryResult | None = None
    error: Exception | None = None
    calls: int = 0
    observed_states: list[DeliveryState] | None = None

    def send(self, delivery: Delivery) -> DeliveryResult:
        self.calls += 1
        if self.observed_states is None:
            self.observed_states = []
        self.observed_states.append(delivery.state)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    def edit(self, delivery: Delivery) -> DeliveryResult:
        raise AssertionError("edit is not part of this send contract")


def test_delivery_starts_pending_and_begin_attempt_enters_attempting() -> None:
    delivery = make_delivery()

    assert delivery.state is DeliveryState.PENDING
    assert delivery.attempts == 0

    delivery.begin_attempt()

    assert delivery.state is DeliveryState.ATTEMPTING
    assert delivery.attempts == 1


def test_successful_transport_moves_delivery_to_delivered_after_attempt() -> None:
    transport = RecordingTransport(result=DeliveryResult(success=True, external_id="remote-1"))
    delivery = make_delivery()

    state = DeliveryService(transport).deliver(delivery)

    assert state is DeliveryState.DELIVERED
    assert delivery.state is DeliveryState.DELIVERED
    assert transport.calls == 1
    assert transport.observed_states == [DeliveryState.ATTEMPTING]


@pytest.mark.parametrize(
    ("retryable", "error"),
    [(True, "temporary"), (False, "permanent")],
)
def test_failed_transport_moves_delivery_to_failed_without_automatic_retry(
    retryable: bool, error: str
) -> None:
    transport = RecordingTransport(
        result=DeliveryResult(success=False, retryable=retryable, error=error)
    )
    delivery = make_delivery()

    state = DeliveryService(transport).deliver(delivery)

    assert state is DeliveryState.FAILED
    assert delivery.state is DeliveryState.FAILED
    assert delivery.attempts == 1
    assert transport.calls == 1
    assert transport.observed_states == [DeliveryState.ATTEMPTING]


def test_delivery_result_preserves_external_id_retryable_and_error_as_transport_data() -> None:
    result = DeliveryResult(
        success=False,
        external_id="remote-ambiguous",
        retryable=True,
        error="timeout-after-accept",
    )

    assert result.success is False
    assert result.external_id == "remote-ambiguous"
    assert result.retryable is True
    assert result.error == "timeout-after-accept"


def test_success_is_required_before_delivered() -> None:
    delivery = make_delivery()

    with pytest.raises(ValueError, match="must be attempting"):
        delivery.mark_delivered()
    assert delivery.state is DeliveryState.PENDING

    delivery.begin_attempt()
    delivery.mark_failed()
    with pytest.raises(ValueError, match="must be attempting"):
        delivery.mark_delivered()
    assert delivery.state is DeliveryState.FAILED


def test_transport_exception_marks_delivery_failed_and_is_re_raised() -> None:
    transport_error = RuntimeError("transport unavailable")
    transport = RecordingTransport(error=transport_error)
    delivery = make_delivery()

    with pytest.raises(RuntimeError, match="transport unavailable") as raised:
        DeliveryService(transport).deliver(delivery)

    assert raised.value is transport_error
    assert delivery.state is DeliveryState.FAILED
    assert delivery.attempts == 1
    assert transport.calls == 1
