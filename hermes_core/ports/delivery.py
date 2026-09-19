"""Transport-independent delivery contract."""

from typing import Protocol

from hermes_core.domain.delivery import Delivery, DeliveryResult


class DeliveryPort(Protocol):
    def send(self, delivery: Delivery) -> DeliveryResult: ...
    def edit(self, delivery: Delivery) -> DeliveryResult: ...
