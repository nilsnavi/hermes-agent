"""Delivery state transitions over a transport port."""

from hermes_core.domain.delivery import Delivery, DeliveryResult, DeliveryState
from hermes_core.ports.delivery import DeliveryPort


class DeliveryService:
    def __init__(self, transport: DeliveryPort) -> None:
        self._transport = transport

    def deliver(self, delivery: Delivery) -> DeliveryState:
        delivery.begin_attempt()
        try:
            result: DeliveryResult = self._transport.send(delivery)
            if result.success:
                delivery.mark_delivered()
            else:
                delivery.mark_failed()
        except Exception:
            delivery.mark_failed()
            raise
        return delivery.state
