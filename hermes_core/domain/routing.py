"""Provider route values with no provider SDK knowledge."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RoutePurpose(str, Enum):
    MAIN = "main"
    COMPRESSION = "compression"
    VISION = "vision"
    TITLE = "title"
    SEARCH = "search"


@dataclass(frozen=True)
class RouteDecision:
    provider: str
    model: str
    endpoint: Optional[str]
    api_mode: str
    credential_reference: Optional[str]
    route_purpose: RoutePurpose
