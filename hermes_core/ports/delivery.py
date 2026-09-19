"""Transport-independent delivery contract."""

from typing import Protocol

from hermes_core.domain.delivery import Delivery


class DeliveryPort(Protocol):
    def send(self, delivery: Delivery) -> bool: ...
    def edit(self, delivery: Delivery) -> bool: ...
