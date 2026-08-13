"""Gateway observe hook for the Intent Router (Sprint 1.1.1 §7-9).

This module is the ONLY bridge between the production gateway and the
router. Contract (hard safety rule, §1):

* ``actual_route`` MUST NOT depend on the router decision — the hook
  only *observes* AFTER the gateway already made its own decision and
  returns ``None`` unless the router is enabled in OBSERVE mode.
* On ANY router exception the hook increments the shared error counter,
  logs one safe line and returns ``None`` — the request proceeds
  normally, the route is unchanged, the user never sees the failure
  (§8).
* The hook persists/logs ONLY the whitelisted scalar fields (§9):
  request_id, intent, risk, expected_side_effect, candidate_route,
  effective_route, actual_route, confidence_bucket, reason_codes,
  required/missing capability counts, matched, router_version,
  policy_version, duration_ms, sample_source. Raw prompt, user message,
  Authorization, cookies, tokens, attachment content and tool args
  NEVER enter the event or the log line.
* The router process-wide singleton keeps in-memory stats + bounded
  event ring across requests (metrics §12-13) without any DB write.

``sample_source`` is taken verbatim from the caller; the gateway passes
``SampleSource.LIVE.value`` for real platform traffic (§10).
"""

from typing import Any, Dict, Optional

from .evaluation import features_from_text
from .models import IntentRoutingDecision, RouterMode
from .router import IntentRouter, RouterEvent, read_router_flags

# Process-wide counters (kept even if the singleton is re-created).
_GLOBAL_OBSERVED = 0
_GLOBAL_ERRORS = 0

_LOGGER_NAME = "gateway.intent_router"

# V2Decision (gateway_v2) → ActualRoute (§11). Values from the routing
# state/code path — never inferred from response text.
_V2_TO_ACTUAL = {
    "legacy": "LEGACY",
    "shadow": "SHADOW",
    "v2_canary": "V2_CANARY",
}


def actual_route_from_v2(v2_decision: Any, internal: bool = False) -> str:
    """Map the gateway's V2Decision + internal marker to ActualRoute.

    ``internal`` requests (operations/status plumbing) are their own
    bucket; anything else falls back to LEGACY (the fail-open decision
    path is LEGACY by construction).
    """
    if internal:
        return "OPERATIONS"
    value = getattr(v2_decision, "value", None)
    return _V2_TO_ACTUAL.get(value, "LEGACY")


def _logger():
    import logging

    return logging.getLogger(_LOGGER_NAME)


def _pid_health() -> Dict[str, Any]:
    """Cheap non-blocking gateway liveness for the policy gate.

    OperationsService.health() (systemctl + DB probes) costs seconds on
    the first call — unacceptable inside a per-request observe hook
    (§21: p95 < 5ms). A pid-file kill(0) probe is sub-ms; canary/shadow
    candidates are denied by default in production observe anyway.
    """
    try:
        import os

        from hermes_constants import get_hermes_home

        pid = int((get_hermes_home() / "gateway.pid").read_text().strip())
        os.kill(pid, 0)
        return {"status": "healthy"}
    except Exception:
        return {"status": "unknown"}


def _get_router() -> IntentRouter:
    """Process-wide lazy singleton — accumulates stats/ring across
    requests so observe metrics are meaningful (§12-14)."""
    global _GLOBAL_ROUTER
    if _GLOBAL_ROUTER is None:
        _GLOBAL_ROUTER = IntentRouter(
            flags=read_router_flags(),
            health_provider=_pid_health,
        )
    return _GLOBAL_ROUTER


_GLOBAL_ROUTER: Optional[IntentRouter] = None


def observe_gateway_event(
    text: str,
    request_id: str = "gateway",
    actual_route: Optional[str] = None,
    sample_source: str = "LIVE",
    router: Optional[IntentRouter] = None,
) -> Optional[IntentRoutingDecision]:
    """Non-authoritative observe hook for the gateway adapter.

    Returns ``None`` when the router is disabled / not in observe mode
    (hook inert, zero overhead) or when the router failed (fail-open,
    §8). Never raises into the caller.
    """
    global _GLOBAL_OBSERVED, _GLOBAL_ERRORS
    flags = read_router_flags()
    mode = flags.get("mode")
    if not flags.get("enabled") or not isinstance(mode, RouterMode):
        return None
    if mode.value != "observe":
        return None
    try:
        r = router if router is not None else _get_router()
        decision = r.observe(
            features_from_text(
                str(text or ""), request_id=request_id,
            ),
            actual_route=actual_route,
            sample_source=sample_source,
        )
        _GLOBAL_OBSERVED += 1
        _log_observation(decision)
        return decision
    except Exception:
        _GLOBAL_ERRORS += 1
        try:
            _logger().warning(
                "gateway.intent_router.observe failed (never breaks "
                "legacy) errors=%d", _GLOBAL_ERRORS,
            )
        except Exception:
            pass
        return None


def calibration_observe(
    text: str,
    request_id: str = "calibration",
    context: Optional["CalibrationSafetyContext"] = None,
    router: Optional[IntentRouter] = None,
) -> Dict[str, Any]:
    """Calibration-sandbox classify + barrier verdict (Sprint 1.1.1.1).

    The ONLY calibration entry point for INTERNAL_SYNTHETIC requests.
    Classifies through the same router, then maps the decision through
    the CalibrationSafetyBarrier. Returns the verdict — it never
    executes anything; the caller must honor the disposition.

    Invariant (§11): classify → recommend → optionally exercise a
    READ_ONLY tool → side-effecting execution FORBIDDEN.

    NOTE: the calibration sandbox is environment-independent by design
    — the CLI process has no gateway env flags, so a router passed in
    (or a fresh one created with explicit observe flags) is used
    directly. The production hook path (observe_gateway_event) is
    unaffected.
    """
    from .calibration_safety import (
        CalibrationSafetyBarrier,
        CalibrationSafetyContext as _Ctx,
    )
    from .models import RouterMode
    from .router import IntentRouter, read_router_flags

    ctx = context or _Ctx(request_id=request_id)
    barrier = CalibrationSafetyBarrier()
    r = router
    if r is None:
        flags = read_router_flags()
        if not flags.get("enabled") or flags.get("mode") != "observe":
            # Sandbox default: explicit observe flags (env-independent).
            flags = {
                **flags,
                "enabled": True,
                "mode": RouterMode.OBSERVE.value,
            }
        r = IntentRouter(flags=flags)
    decision = r.observe(
        features_from_text(str(text or ""), request_id=request_id),
        actual_route="LEGACY",
        sample_source=ctx.sample_source,
    )
    verdict = barrier.evaluate(decision, context=ctx)
    return {
        "ok": True,
        "request_id": request_id,
        "decision": decision.to_dict(),
        "verdict": verdict.to_dict(),
        "allowed_read_only": verdict.allowed_read_only,
        "denied": verdict.denied,
    }


def _log_observation(decision: IntentRoutingDecision) -> None:
    """One structured safe log line (§9) — no prompt, no args."""
    try:
        _logger().info(
            "gateway.intent_router.observe request_id=%s intent=%s "
            "risk=%s side_effect=%s candidate=%s effective=%s "
            "actual=%s matched=%s bucket=%s reasons=%s "
            "required_caps=%d missing_caps=%d sample=%s "
            "duration_ms=%s router=%s policy=%s",
            decision.request_id,
            decision.intent,
            decision.risk,
            decision.expected_side_effect,
            decision.candidate_route,
            decision.effective_route,
            decision.actual_route,
            decision.matched,
            decision.to_dict().get("confidence_bucket"),
            ",".join(decision.reason_codes or []),
            len(decision.required_capabilities),
            len(decision.missing_capabilities),
            decision.sample_source,
            decision.duration_ms,
            decision.classifier_version,
            decision.policy_version,
        )
    except Exception:
        pass  # logging must never break the request


def observe_metrics() -> Dict[str, Any]:
    """Process-wide observe counters for operator tooling (§12-13)."""
    try:
        stats = _get_router().stats()
    except Exception:
        stats = {}
    return {
        "router_observations_total": _GLOBAL_OBSERVED,
        "router_errors": _GLOBAL_ERRORS,
        "router_matches": stats.get("matches", 0),
        "router_policy_mismatches": stats.get("policy_mismatches", 0),
        "router_classification_reviews": stats.get(
            "classification_reviews", 0),
        "recommended": stats.get("recommended", {}),
        "actual": stats.get("actual", {}),
        "decisions": stats.get("decisions", 0),
    }


def router_health() -> Dict[str, Any]:
    """Process-wide router health (§14)."""
    try:
        return _get_router().health()
    except Exception:
        return {
            "level": "UNKNOWN", "enabled": False, "mode": "off",
            "observations": _GLOBAL_OBSERVED,
            "errors": _GLOBAL_ERRORS,
            "error_rate": None,
            "unsafe_canary_recommendations": None,
            "unsafe_predicted_read_only": None,
            "p50_ms": None,
            "p95_ms": None,
        }


__all__ = [
    "observe_gateway_event",
    "calibration_observe",
    "observe_metrics",
    "router_health",
    "RouterEvent",
]
