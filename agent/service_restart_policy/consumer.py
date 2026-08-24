"""Fail-closed restart consumer classification policy."""
from __future__ import annotations

from .models import ConsumerClass


class RestartConsumerPolicy:
    ALLOWED = frozenset({ConsumerClass.NONE, ConsumerClass.PASSIVE, ConsumerClass.NON_CRITICAL})

    def allowed(self, consumer: ConsumerClass) -> bool:
        try:
            normalized = ConsumerClass(consumer)
        except (TypeError, ValueError):
            return False
        return normalized in self.ALLOWED


__all__ = ["RestartConsumerPolicy"]
