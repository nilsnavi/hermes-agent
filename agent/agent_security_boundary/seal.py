"""Sandbox adapter sealing.

The sandbox adapter is RUNTIME-OWNED and sealed: it never accepts a caller
supplied executable/command/callback/verdict, and it is not exposed through any
public API. The only way to reach the underlying adapter is through the security
gate, which holds a private, never-exported gate token. Any direct invocation
from outside the gate raises ``SealViolation`` (direct adapter call DENIED).
"""

from __future__ import annotations

from typing import Any

from .exceptions import SealViolation
from .ports import SandboxAdapterSeam

# A private, module-local token proving the caller is the gate itself. It is
# NEVER exported, NEVER returned by any method, and has NO public accessor, so
# no external caller (holding only the SealedSandbox wrapper) can ever obtain it.
# Given the wrapper plus an unobtainable token, `run` is effectively uncallable
# from outside — the sealed property is real, not theatrical. A future
# execution-bind layer (Phase 6+) will introduce a controlled, authenticated
# invocation seam; in this non-executing phase `run` stays denied for everyone.
_GATE_TOKEN = object()


class SealedSandbox:
    """Sealed wrapper over a runtime-owned sandbox adapter.

    ``run`` is reachable only with the private gate token. Admission (the only
    action this phase performs) never invokes ``run``; it merely certifies that a
    sealed sandbox is present and available. So real adapter calls stay 0.
    """

    __slots__ = ("_adapter", "_calls")

    def __init__(self, adapter: SandboxAdapterSeam | None = None) -> None:
        self._adapter = adapter
        self._calls = 0

    @property
    def is_present(self) -> bool:
        return self._adapter is not None

    @property
    def is_sealed(self) -> bool:
        return True

    @property
    def call_count(self) -> int:
        """Number of actual adapter invocations (must stay 0 in this phase)."""
        return self._calls

    def run(self, payload: Any, *, gate_token: object = None) -> Any:
        """Sealed invocation. DENIED unless the private gate token is supplied.

        The token has no public accessor in this module (no classmethod, no
        attribute, not in ``__all__``), so no caller reaching only this wrapper
        can obtain it. Any direct adapter attempt raises ``SealViolation`` and
        the underlying adapter is never invoked.
        """
        if gate_token is not _GATE_TOKEN:
            raise SealViolation("direct sandbox adapter call is denied")
        if self._adapter is None:
            raise SealViolation("no sandbox adapter is configured")
        self._calls += 1
        return self._adapter.run(payload)

    @classmethod
    def _gate_token(cls) -> object:  # pragma: no cover - removed accessor
        """Deprecated: previously returned the private token.

        REMOVED BY DESIGN (BLOCKING B1 closure). The token must have NO public
        accessor; returning it from a classmethod made the sealed sandbox
        directly invocable, bypassing the entire mandatory execution path. This
        stub exists only so a historical call raises clearly instead of
        silently succeeding; it no longer returns the token.
        """
        raise AttributeError(
            "_gate_token is removed: the seal token has no public accessor"
        )


__all__ = ["SealedSandbox"]