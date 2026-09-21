"""Delivery obligation state machine."""

from dataclasses import dataclass
from enum import Enum


class DeliveryState(str, Enum):
    PENDING = "pending"
    ATTEMPTING = "attempting"
    DELIVERED = "delivered"
    FAILED = "failed"
    UNKNOWN_ACK = "unknown_ack"
    ABANDONED = "abandoned"


class DeliveryOutcome(str, Enum):
    CONFIRMED_SUCCESS = "confirmed_success"
    CONFIRMED_FAILURE = "confirmed_failure"
    UNKNOWN_ACK = "unknown_ack"


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    external_id: str | None = None
    retryable: bool = False
    error: str | None = None
    outcome: DeliveryOutcome | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.outcome is None:
            object.__setattr__(
                self,
                "outcome",
                DeliveryOutcome.CONFIRMED_SUCCESS
                if self.success
                else DeliveryOutcome.CONFIRMED_FAILURE,
            )
        elif (self.outcome is DeliveryOutcome.CONFIRMED_SUCCESS) != self.success:
            raise ValueError("success flag contradicts delivery outcome")


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

    def mark_unknown(self) -> None:
        if self.state is not DeliveryState.ATTEMPTING:
            raise ValueError("delivery must be attempting before ambiguous acknowledgement")
        self.state = DeliveryState.UNKNOWN_ACK

    def reconcile_delivered(self) -> None:
        if self.state is not DeliveryState.UNKNOWN_ACK:
            raise ValueError("only unknown acknowledgement can be reconciled")
        self.state = DeliveryState.DELIVERED

    def reconcile_failed(self) -> None:
        if self.state is not DeliveryState.UNKNOWN_ACK:
            raise ValueError("only unknown acknowledgement can be reconciled")
        self.state = DeliveryState.FAILED

    def abandon(self) -> None:
        if self.state is not DeliveryState.UNKNOWN_ACK:
            raise ValueError("only unknown acknowledgement can be abandoned")
        self.state = DeliveryState.ABANDONED
