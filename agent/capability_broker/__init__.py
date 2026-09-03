"""Scoped, deny-by-default integration Capability Broker foundation."""

from .broker import CapabilityBroker
from .config import CapabilityBrokerConfig
from .context import TrustedCapabilityContext, TrustedSurface
from .models import (
    CapabilityOperationRequest,
    CapabilityResponse,
    CapabilityResult,
)
from .registry import CapabilityDefinition, CapabilityRegistry
from .registry_factory import build_testit_read_registry

__all__ = [
    "CapabilityBroker",
    "CapabilityBrokerConfig",
    "CapabilityDefinition",
    "CapabilityOperationRequest",
    "CapabilityRegistry",
    "CapabilityResponse",
    "CapabilityResult",
    "TrustedCapabilityContext",
    "TrustedSurface",
    "build_testit_read_registry",
]
