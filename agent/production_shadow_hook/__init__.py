"""Phase 8 -- Controlled Production Shadow Hook (implementation only).

A minimal ONE-WAY, bounded, non-blocking shadow tap from the production path into
the Phase 7 ShadowRuntime. The hook only sanitizes/copies bounded metadata,
enqueues (never waiting on shadow) and records success/drop. All shadow
processing stays in ``agent.platform_shadow``.

CRITICAL INVARIANT (production request -> production response, production itself
=> shadow tap): the shadow hook can NEVER modify the production request/response,
block or delay production completion, run mutations, call an executor, grant
authority, change scheduler/provider/config, write production state, or restart
services. There is NO API to apply/replace/override/promote a shadow result into
production (PRODUCTION_RETURN_PATHS=0).

Production activation is OFF in Phase 8: LIVE_SHADOW_ACTIVATION=False.
READY != AUTHORIZED: cargo only after an explicit operator gate.
"""

from .consumer import ShadowHookConsumer
from .envelope import (
    FORBIDDEN_SUBSTRINGS,
    ProductionShadowEnvelope,
    assert_no_forbidden_content,
)
from .exceptions import (
    EnvelopeRejectedError,
    HookDisabledError,
    HookError,
    QueueUnavailableError,
)
from .hook import EnqueueOutcome, ProductionShadowHook
from .metrics import SHADOW_HOOK_METRIC_NAMES, ShadowHookMetrics
from .modes import (
    ENABLED_ENV,
    KILL_SWITCH_ENV,
    HookConfiguration,
    HookMode,
    default_hook_enabled,
    default_kill_switch,
)
from .redaction import ALLOWED_CONTEXT_KEYS, sanitize_context
from .transport import InMemoryBoundedQueue, ShadowTransport

LIVE_SHADOW_ACTIVATION = False  # Phase 8: implementation only, no live hook.
READY_NOT_AUTHORIZED = True


def _make_default_config() -> HookConfiguration:
    return HookConfiguration()  # enabled=False, kill_switch=True -> inactive by default


__all__ = [
    "ALLOWED_CONTEXT_KEYS",
    "ENABLED_ENV",
    "FORBIDDEN_SUBSTRINGS",
    "EnqueueOutcome",
    "EnvelopeRejectedError",
    "HookConfiguration",
    "HookDisabledError",
    "HookError",
    "HookMode",
    "InMemoryBoundedQueue",
    "KILL_SWITCH_ENV",
    "LIVE_SHADOW_ACTIVATION",
    "ProductionShadowEnvelope",
    "ProductionShadowHook",
    "QueueUnavailableError",
    "READY_NOT_AUTHORIZED",
    "SHADOW_HOOK_METRIC_NAMES",
    "ShadowHookConsumer",
    "ShadowHookMetrics",
    "ShadowTransport",
    "assert_no_forbidden_content",
    "default_hook_enabled",
    "default_kill_switch",
    "sanitize_context",
]