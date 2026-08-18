"""Operation classifier (Sprint 1.3.3 §11).

Deterministic operation classification from a command line — a thin
layer over effective_action for callers that need the operation class
in isolation.
"""

from typing import Optional

from . import effective_action as ea
from .models import OperationClass


class OperationClassifier:
    """Deterministic operation classification."""

    def classify(self, command: str) -> OperationClass:
        return ea.classify_command(command).operation_class

    def is_read(self, command: str) -> bool:
        return not ea.classify_command(command).is_mutation


#: module-level convenience
classifier = OperationClassifier()


def classify_operation(command: str) -> OperationClass:
    return classifier.classify(command)


__all__ = ["OperationClassifier", "classifier", "classify_operation"]
