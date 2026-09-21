"""Delivery state transitions over a transport port."""

from dataclasses import dataclass
from enum import Enum

from hermes_core.domain.delivery import Delivery, DeliveryResult, DeliveryState, DeliveryOutcome
from hermes_core.ports.delivery import DeliveryPort, DeliveryTransportError


class DeliveryApplicationStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN_ACK = "unknown_ack"
    REJECTED = "rejected"
    TRANSPORT_ERROR = "transport_error"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class DeliveryApplicationResult:
    status: DeliveryApplicationStatus
    state: DeliveryState
    external_id: str | None = None
    retryable: bool = False
    error: str | None = None
    error_code: str | None = None


class DeliveryService:
    def __init__(self, transport: DeliveryPort) -> None:
        self._transport = transport

    def deliver(self, delivery: Delivery) -> DeliveryState:
        return self.deliver_result(delivery).state

    def deliver_result(self, delivery: Delivery) -> DeliveryApplicationResult:
        delivery.begin_attempt()
        try:
            result: DeliveryResult = self._transport.send(delivery)
            if result.outcome is DeliveryOutcome.CONFIRMED_SUCCESS:
                delivery.mark_delivered()
                status = DeliveryApplicationStatus.SUCCESS
            elif result.outcome is DeliveryOutcome.CONFIRMED_FAILURE:
                delivery.mark_failed()
                status = DeliveryApplicationStatus.FAILURE
            else:
                delivery.mark_unknown()
                status = DeliveryApplicationStatus.UNKNOWN_ACK
            return DeliveryApplicationResult(status, delivery.state, result.external_id,
                                             result.retryable, result.error, result.error_code)
        except DeliveryTransportError as exc:
            delivery.mark_unknown()
            return DeliveryApplicationResult(DeliveryApplicationStatus.TRANSPORT_ERROR,
                                             delivery.state, exc.external_id, exc.retryable,
                                             exc.reason, "ambiguous_transport")

    @staticmethod
    def reconcile_delivered(delivery: Delivery) -> DeliveryApplicationResult:
        try:
            delivery.reconcile_delivered()
        except ValueError:
            return DeliveryApplicationResult(DeliveryApplicationStatus.REJECTED, delivery.state)
        return DeliveryApplicationResult(DeliveryApplicationStatus.SUCCESS, delivery.state)

    @staticmethod
    def reconcile_failed(delivery: Delivery) -> DeliveryApplicationResult:
        try:
            delivery.reconcile_failed()
        except ValueError:
            return DeliveryApplicationResult(DeliveryApplicationStatus.REJECTED, delivery.state)
        return DeliveryApplicationResult(DeliveryApplicationStatus.FAILURE, delivery.state)

    @staticmethod
    def abandon(delivery: Delivery) -> DeliveryApplicationResult:
        try:
            delivery.abandon()
        except ValueError:
            return DeliveryApplicationResult(DeliveryApplicationStatus.REJECTED, delivery.state)
        return DeliveryApplicationResult(DeliveryApplicationStatus.ABANDONED, delivery.state)
