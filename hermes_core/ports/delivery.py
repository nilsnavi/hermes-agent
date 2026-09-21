"""Transport-independent delivery contract."""

from typing import Protocol

from hermes_core.domain.delivery import Delivery, DeliveryResult


class DeliveryTransportError(Exception):
    """Ambiguous provider-neutral outcome: side effect may have occurred.

    Success/failure cannot be established, so the application classifies it as
    UNKNOWN_ACK and does not treat retry as automatically safe.
    """

    def __init__(self, reason: str, *, retryable: bool = False, external_id: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.external_id = external_id


class DeliveryPort(Protocol):
    def send(self, delivery: Delivery) -> DeliveryResult: ...
    def edit(self, delivery: Delivery) -> DeliveryResult: ...
