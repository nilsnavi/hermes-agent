"""Hermes Agent 2.0 — Gateway V2 Adapter (Sprint 1.0.6).

The first safe bridge between the production gateway and the V2 runtime:

    LEGACY REQUEST ─► legacy runtime (UNCHANGED, default)
    V2-CANARY REQUEST ─► GatewayV2Adapter ─► RuntimeOrchestrator ─►
                        SQLiteExecutionStore ─► controlled read-only execution

PRINCIPLE: DEFAULT = LEGACY. All ``HERMES_RUNTIME_V2_*`` flags default to
false; V2 activates ONLY explicitly. With flags false the adapter returns
LEGACY in microseconds, opens nothing, and changes zero behavior.

Fallback invariant: legacy fallback is allowed only BEFORE any V2 side
effect; once TOOL_STARTED exists in the journal, fallback is forbidden
(no silent duplicate actions).
"""

from .adapter import (
    GatewayV2Adapter,
    V2Decision,
    gateway_v2_adapter_singleton,
    get_default_adapter,
)
from .canary import SafeCanaryToolRegistry, V2CanaryPolicy
from .context_builder import GatewayRequest, GatewayTaskContextBuilder
from .events import EVENT_TYPES, V2Telemetry
from .exceptions import (
    V2ErrorBase,
    V2FallbackForbidden,
    V2NotEligible,
    V2NotEnabled,
)
from .flags import FLAG_NAMES, FeatureFlags, parse_flag, read_flags
from .result_mapper import V2ResultMapper
from .shadow import ShadowRunner
from .store_factory import RuntimeV2StoreFactory, schema_apply, schema_check

__all__ = [
    "GatewayV2Adapter",
    "V2Decision",
    "GatewayRequest",
    "GatewayTaskContextBuilder",
    "V2CanaryPolicy",
    "SafeCanaryToolRegistry",
    "V2ResultMapper",
    "ShadowRunner",
    "RuntimeV2StoreFactory",
    "V2Telemetry",
    "FeatureFlags",
    "parse_flag",
    "read_flags",
    "FLAG_NAMES",
    "schema_check",
    "schema_apply",
    "get_default_adapter",
    "gateway_v2_adapter_singleton",
    "V2ErrorBase",
    "V2NotEnabled",
    "V2NotEligible",
    "V2FallbackForbidden",
    "EVENT_TYPES",
]
