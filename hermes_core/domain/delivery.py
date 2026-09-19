"""Delivery obligation state machine."""

from dataclasses import dataclass
from enum import Enum


class DeliveryState(str, Enum):
    PENDING = "pending"
    ATTEMPTING = "attempting"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass
class Delivery:
    obligation_id: str
    session_key: str
    content: str
    state: DeliveryState = DeliveryState.PENDING
    attempts: int = 0

    def begin_attempt(self) -> None:
        if self.state is not DeliveryState.PENDING:
            raise ValueError("delivery can only be attempted from pending")
        self.state = DeliveryState.ATTEMPTING
        self.attempts += 1

    def mark_delivered(self) -> None:
        if self.state is not DeliveryState.ATTEMPTING:
            raise ValueError("delivery must be attempting before acknowledgement")
        self.state = DeliveryState.DELIVERED

    def mark_failed(self) -> None:
        if self.state is not DeliveryState.ATTEMPTING:
            raise ValueError("delivery must be attempting before failure")
        self.state = DeliveryState.FAILED
