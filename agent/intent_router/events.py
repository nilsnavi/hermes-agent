"""Intent Router event types (Sprint 1.1 §40) + safe event builder.

Event OBJECTS are the existing :class:`agent.runtime.events.RuntimeEvent`
so router observations join the SAME audit stream. Fields are whitelisted
scalars — a raw prompt, authorization, token, tool args or full metadata
never appear.

Observe mode MUST NOT persist a row per ordinary request in state.db;
events are emitted into an in-memory bounded ring (or a structured log
provided by the caller). See :mod:`agent.intent_router.router`.
"""

from typing import Any, Dict, Optional

INTENT_ROUTER_EVALUATED = "intent_router.evaluated"
INTENT_ROUTER_ERROR = "intent_router.error"
INTENT_ROUTER_MISMATCH = "intent_router.mismatch"

ROUTER_EVENT_TYPES = frozenset(
    {
        INTENT_ROUTER_EVALUATED,
        INTENT_ROUTER_ERROR,
        INTENT_ROUTER_MISMATCH,
    }
)


def router_event_payload(
    request_id: str,
    intent: Optional[str],
    risk: Optional[str],
    candidate_route: Optional[str],
    effective_route: Optional[str],
    confidence: Optional[float],
    reason_codes: list,
    capabilities: Optional[list],
    duration_ms: Optional[float],
    router_version: str,
    mode: str,
    expected_side_effect: Optional[str] = None,
    actual_route: Optional[str] = None,
    matched: Optional[bool] = None,
    missing_capabilities: Optional[list] = None,
    sample_source: Optional[str] = None,
    policy_version: Optional[str] = None,
) -> Dict[str, Any]:
    """Whitelisted event payload — NO prompt, NO args, NO metadata.

    Sprint 1.1.1 §9 adds actual_route / matched / sample_source /
    counts; all are scalars or small enumerated lists. Raw user text,
    Authorization, cookies, tokens, attachments and tool args never
    appear.
    """
    missing = list(missing_capabilities or [])
    return {
        "request_id": request_id,
        "intent": intent,
        "risk": risk,
        "expected_side_effect": expected_side_effect,
        "candidate_route": candidate_route,
        "effective_route": effective_route,
        "actual_route": actual_route,
        "confidence": confidence,
        "confidence_bucket": _bucket(confidence),
        "reason_codes": list(reason_codes or []),
        "required_capability_count": len(list(capabilities or [])),
        "missing_capability_count": len(missing),
        "matched": matched,
        "duration_ms": duration_ms,
        "router_version": router_version,
        "policy_version": policy_version,
        "mode": mode,
        "sample_source": sample_source,
    }


def router_error_payload(
    request_id: str,
    error_class: str,
    router_version: str,
    mode: str,
) -> Dict[str, Any]:
    return {
        "request_id": request_id,
        "error_class": error_class,
        "router_version": router_version,
        "mode": mode,
    }


def _bucket(confidence: Optional[float]) -> Optional[str]:
    from .models import confidence_bucket

    return confidence_bucket(confidence)
