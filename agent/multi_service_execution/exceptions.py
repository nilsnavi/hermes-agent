"""Sprint 1.3.17 — module exceptions."""

from __future__ import annotations


class MultiServiceExecutionError(Exception):
    """Base error for the bounded multi-service execution package."""


class ExecutionDisabled(MultiServiceExecutionError):
    """All real execution is disabled; this is the fail-closed terminal."""


class AuthorityDenied(MultiServiceExecutionError):
    """Authority missing / foreign / copy-forged / single-use already consumed."""


class InvalidExecutionPlan(MultiServiceExecutionError):
    """Execution plan failed revalidation (drift, missing binding)."""


class RevalidateRequired(MultiServiceExecutionError):
    """A gate requires fresh revalidation; no execution may proceed."""


class DevelopmentGateError(MultiServiceExecutionError):
    """Internal state machine misuse (illegal transition detected)."""


class ReceiptStoreError(MultiServiceExecutionError):
    """Durable receipt store is unreadable or inconsistent."""


__all__ = [
    "MultiServiceExecutionError",
    "ExecutionDisabled",
    "AuthorityDenied",
    "InvalidExecutionPlan",
    "RevalidateRequired",
    "DevelopmentGateError",
    "ReceiptStoreError",
]