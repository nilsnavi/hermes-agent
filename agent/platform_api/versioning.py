"""API versioning contracts.

The platform API is versioned. Every request must declare a supported version
(either via a versioned path prefix or an explicit version header), and the
version must be one the server can honour. Unknown or unsupported versions are
rejected fail-closed: the caller cannot silently fall back to an older or
future contract.
"""

from __future__ import annotations

from dataclasses import dataclass


class InvalidApiVersion(ValueError):
    """Raised when an API version is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class ApiVersion:
    major: int
    minor: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.major, bool) or not isinstance(self.major, int) or self.major < 1:
            raise InvalidApiVersion("major must be a positive integer")
        if (
            isinstance(self.minor, bool)
            or not isinstance(self.minor, int)
            or self.minor < 0
        ):
            raise InvalidApiVersion("minor must be a non-negative integer")

    @property
    def prefix(self) -> str:
        return f"v{self.major}"

    @classmethod
    def parse(cls, raw: object) -> "ApiVersion":
        if not isinstance(raw, str):
            raise InvalidApiVersion("api version must be a string")
        text = raw.strip()
        if text.startswith("v"):
            text = text[1:]
        parts = text.split(".")
        try:
            numbers = [int(part) for part in parts]
        except ValueError as exc:
            raise InvalidApiVersion(f"malformed api version {raw!r}") from exc
        if not numbers or len(numbers) > 2 or numbers[0] < 1:
            raise InvalidApiVersion(f"malformed api version {raw!r}")
        minor = numbers[1] if len(numbers) == 2 else 0
        if minor < 1 and len(numbers) == 2:
            raise InvalidApiVersion(f"minor must be positive when provided: {raw!r}")
        return cls(numbers[0], minor)


def parse_request_version(
    raw: object, *, supported: frozenset[ApiVersion]
) -> ApiVersion:
    if not isinstance(supported, frozenset) or not supported:
        raise InvalidApiVersion("supported versions must be a non-empty frozenset")
    for supported_version in supported:
        if type(supported_version) is not ApiVersion:
            raise InvalidApiVersion(
                "supported versions must contain exact ApiVersion values"
            )
    version = ApiVersion.parse(raw)
    if version not in supported:
        raise InvalidApiVersion(f"unsupported api version {raw!r}")
    return version