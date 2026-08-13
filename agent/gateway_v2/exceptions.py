"""Gateway V2 exceptions (Sprint 1.0.6)."""


class V2ErrorBase(Exception):
    """Base class for gateway-adapter errors."""


class V2NotEnabled(V2ErrorBase):
    """V2 runtime is disabled by feature flags."""


class V2NotEligible(V2ErrorBase):
    """Request is not eligible for the V2 canary path."""


class V2FallbackForbidden(V2ErrorBase):
    """Legacy fallback is forbidden after a V2 side effect may have run.

    Once TOOL_STARTED exists in the journal, silently re-running the
    request through legacy could DUPLICATE the external action.
    """


class ShadowToolExecutionForbidden(V2ErrorBase):
    """A shadow-mode tool handler was invoked — strictly forbidden (§20).

    Shadow mode may inspect registries, validate plans and predict
    outcomes, but MUST NEVER execute a ToolRuntime handler. Raised by
    :class:`agent.gateway_v2.shadow.NoExecuteToolRegistry` and by every
    diagnostic shadow handler if one is ever called. A raised
    ShadowToolExecutionForbidden is a test failure, never a silent
    fallback.
    """


__all__ = [
    "V2ErrorBase",
    "V2NotEnabled",
    "V2NotEligible",
    "V2FallbackForbidden",
    "ShadowToolExecutionForbidden",
]
