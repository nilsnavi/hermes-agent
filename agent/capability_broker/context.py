"""Trusted runtime context for capability execution.

The request payload is deliberately NOT an identity source. Principal is
produced by the existing authenticated Platform API boundary. Surface is a
closed value supplied by the trusted runtime adapter, never a free-form field
inside CapabilityOperationRequest.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent.platform_api.auth import Principal

from .errors import InvalidTrustedContext


class TrustedSurface(str, Enum):
    DESKTOP = "desktop"
    WEBUI = "webui"


_MAX_REQUEST_ID = 256


@dataclass(frozen=True, slots=True)
class TrustedCapabilityContext:
    principal: Principal
    surface: TrustedSurface
    request_id: str

    def __post_init__(self) -> None:
        if type(self.principal) is not Principal:
            raise InvalidTrustedContext(
                "principal must be an exact authenticated Principal"
            )
        if type(self.surface) is not TrustedSurface:
            raise InvalidTrustedContext(
                "surface must be an exact TrustedSurface"
            )
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise InvalidTrustedContext(
                "request_id must be a non-empty string"
            )
        if len(self.request_id) > _MAX_REQUEST_ID:
            raise InvalidTrustedContext(
                f"request_id exceeds {_MAX_REQUEST_ID} characters"
            )
