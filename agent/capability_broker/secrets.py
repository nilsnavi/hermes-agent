"""Capability-scoped secret access.

The low-level Hermes secret provider remains agent.secret_scope.get_secret.
This module adds a strict capability-specific allowlist and an opaque value
which cannot accidentally reveal credentials through str/repr.

Secret names originate from trusted registry definitions only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from agent.secret_scope import get_secret

from .errors import SecretAccessDenied, SecretUnavailable


@dataclass(frozen=True, slots=True)
class SecretValue:
    """Opaque credential wrapper.

    str() and repr() are permanently redacted. The actual value can only be
    obtained through the intentionally explicit internal reveal method.
    """

    _value: str

    def __post_init__(self) -> None:
        if not isinstance(self._value, str) or not self._value:
            raise ValueError("secret value must be a non-empty string")

    def __str__(self) -> str:
        return "[REDACTED]"

    def __repr__(self) -> str:
        return "SecretValue([REDACTED])"

    def _reveal_for_integration(self) -> str:
        return self._value


SecretBackend = Callable[[str], str | None]


def hermes_secret_backend(name: str) -> str | None:
    """Trusted adapter around the canonical Hermes secret primitive."""
    value = get_secret(name)
    if value is None:
        return None
    return str(value)


class ScopedSecretResolver:
    """Resolve only names explicitly allowed by a trusted capability definition."""

    def __init__(
        self,
        allowed_names: frozenset[str],
        *,
        backend: SecretBackend = hermes_secret_backend,
    ) -> None:
        if not allowed_names:
            raise ValueError("allowed_names must not be empty")

        checked: set[str] = set()
        for name in allowed_names:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("secret names must be non-empty strings")
            checked.add(name)

        if not callable(backend):
            raise TypeError("backend must be callable")

        self._allowed_names = frozenset(checked)
        self._backend = backend

    @property
    def allowed_names(self) -> frozenset[str]:
        return self._allowed_names

    def resolve(self, name: str) -> SecretValue:
        if name not in self._allowed_names:
            raise SecretAccessDenied("secret is outside capability scope")

        try:
            value = self._backend(name)
        except Exception as exc:
            raise SecretUnavailable(
                "secret backend unavailable"
            ) from exc

        if not isinstance(value, str) or not value:
            raise SecretUnavailable("required secret unavailable")

        return SecretValue(value)

    def resolve_required(self) -> Mapping[str, SecretValue]:
        return {
            name: self.resolve(name)
            for name in sorted(self._allowed_names)
        }
