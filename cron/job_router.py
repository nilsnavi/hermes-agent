"""Scoped Model-Router adapter for scheduled jobs (Sprint 0.6, §12–§15).

Why a separate adapter instead of turning on the global router: the global
flags (HERMES_PROVIDER_REGISTRY_V2 / HERMES_MODEL_ROUTER_V2) stay off so the
interactive chat path remains 100% legacy.  Only the scheduler path, and only
jobs that carry an explicit ``model_profile`` and no explicit pin, may use the
router — gated by its own scoped flag:

    HERMES_SCHEDULED_JOB_MODEL_ROUTER_V2  (default: false)

Precedence policy (§8):
    1. explicit admin pin (job.provider AND job.model)   → never routed
    2. job.modelProfile (scoped flag on)                 → Model Router
    3. legacy job provider/model (unpinned → global default)
    4. global default (config.yaml)

Snapshots (provider_snapshot / model_snapshot) are diagnostic metadata, NOT an
execution contract: a profile-based job ignores stale snapshots (§9).
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

# Scheduled-job scoped flag — NEVER the global HERMES_MODEL_ROUTER_V2.
FLAG_ENV = "HERMES_SCHEDULED_JOB_MODEL_ROUTER_V2"
VALID_PROFILES = ("FAST", "BALANCED", "REASONING", "CODING")
_TRUTHY = ("1", "true", "yes", "on")

# Non-retryable error markers for job retry policy (§25).
NON_RETRYABLE_MARKERS = (
    "AUTH_INVALID",
    "AUTH_EXPIRED",
    "GEO_BLOCKED",
    "WAF_BLOCKED",
    "MODEL_UNSUPPORTED",
    "NO_ROUTE_AVAILABLE",
)


class JobRoutingError(RuntimeError):
    """Raised when a profile-based job cannot be routed (incl. NO_ROUTE)."""


def scheduled_router_enabled(env: Optional[Dict[str, str]] = None) -> bool:
    src = env if env is not None else os.environ
    return src.get(FLAG_ENV, "").strip().lower() in _TRUTHY


def job_profile_id(job: dict) -> Optional[str]:
    pid = (job.get("model_profile") or "").strip().upper()
    return pid if pid in VALID_PROFILES else None


def job_has_explicit_pin(job: dict) -> bool:
    """Explicit admin pin = BOTH provider and model set on the job record."""
    return bool((job.get("provider") or "").strip()) and bool((job.get("model") or "").strip())


def profile_route_applies(job: dict, env: Optional[Dict[str, str]] = None) -> bool:
    """True when this job should use the Model Router this tick.

    Applies only to: valid model_profile AND scoped flag on AND no explicit
    pin.  Script-only / watchdog jobs (no model_profile) are never routed.
    """
    if not scheduled_router_enabled(env):
        return False
    if job_profile_id(job) is None:
        return False
    if job_has_explicit_pin(job):
        return False
    return True


def _registry_from_config():
    from agent.provider_registry import ProviderRegistry
    from agent.provider_registry.bootstrap import build_registry

    reg = ProviderRegistry()
    build_registry(reg)  # configured providers, no network, no probes
    return reg


def route_job_profile(profile: str, job: Optional[dict] = None, registry=None):
    """Resolve a profile to (provider, model) via Model Router.

    Returns a dict {provider, model, reasonCode, reason, healthStatus,
    fallbackCandidates}.  Raises JobRoutingError on unknown profile or
    NO_ROUTE_AVAILABLE — a clear routing failure, never a generic traceback
    and never a legacy broken-fallback chain.
    """
    from agent.model_router import ModelRouter

    pid = (profile or "").strip().upper()
    if pid not in VALID_PROFILES:
        raise JobRoutingError(f"UNKNOWN_PROFILE: model_profile={profile!r} "
                              f"(allowed: {', '.join(VALID_PROFILES)})")
    reg = registry if registry is not None else _registry_from_config()
    router = ModelRouter(registry=reg)
    decision = router.route_model(profile=pid)
    if not (decision.ok and decision.provider and decision.model):
        raise JobRoutingError(
            f"NO_ROUTE_AVAILABLE for model_profile={pid} — "
            f"{decision.reason or 'no eligible provider/model'} "
            f"(fallbackCandidates={len(decision.fallbackCandidates)})"
        )
    return {
        "provider": decision.provider,
        "model": decision.model,
        "reasonCode": decision.reasonCode,
        "reason": decision.reason,
        "healthStatus": decision.registryHealth or "unknown",
        "fallbackCandidates": [
            {"provider": c.provider, "model": c.model}
            for c in decision.fallbackCandidates
        ],
    }


def retry_policy(error_text: str) -> str:
    """Classify job-generation errors for retry (§25).

    retryable: timeout / transient network / provider 5xx / rate limit.
    non_retryable: auth/geo/WAF/unsupported/no-route — repeating is useless.
    """
    text = (error_text or "").upper()
    if any(m in text for m in NON_RETRYABLE_MARKERS):
        return "non_retryable"
    return "retryable"


def attach_profile(job: dict, profile: str) -> dict:
    """Add backward-compatible model_profile without touching schedule,
    name, delivery target, pins or snapshots (used by migration + tests)."""
    out = dict(job)
    out["model_profile"] = profile.upper()
    return out


# ── CLI: dry-run preview (§14) ──────────────────────────────────────────────
def _load_job_by_id(job_id: str) -> Optional[dict]:
    from cron.jobs import load_jobs

    for j in load_jobs():
        if j.get("id") == job_id:
            return j
    return None


def preview(job_id: str, env: Optional[Dict[str, str]] = None) -> int:
    """Route preview for a stored job — no inference, no delivery."""
    job = _load_job_by_id(job_id)
    if job is None:
        print(f"job not found: {job_id}")
        return 2
    pid = job_profile_id(job)
    legacy_provider = job.get("provider") or job.get("provider_snapshot") or "-"
    legacy_model = job.get("model") or job.get("model_snapshot") or "-"
    print(f"Job:            {job.get('name', job_id)} ({job_id})")
    print(f"Profile:        {pid or 'N/A'}")
    print(f"Legacy provider:{legacy_provider}")
    print(f"Legacy model:   {legacy_model}")
    if profile_route_applies(job, env):
        assert pid is not None  # profile_route_applies guarantees it
        try:
            r = route_job_profile(pid, job)
            print(f"Router provider:{r['provider']}")
            print(f"Router model:   {r['model']}")
            print(f"Health:         {r['healthStatus']}")
            print(f"Reason:         {r['reasonCode']} ({r['reason']})")
            print("Would execute:  YES")
        except JobRoutingError as e:
            print(f"Router provider:-")
            print(f"Router model:   -")
            print(f"Health:         -")
            print(f"Reason:         {e}")
            print("Would execute:  NO")
        return 0
    print("Router provider:-")
    print("Router model:   -")
    print("Health:         -")
    print("Reason:         legacy path (flag off, no profile, or explicit pin)")
    print("Would execute:  YES (legacy)")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m cron.job_router",
        description="Scheduled-job Model Router dry-run (no inference, no delivery)")
    parser.add_argument("--job-id", required=True, help="job id from cron/jobs.json")
    args = parser.parse_args()
    raise SystemExit(preview(args.job_id))
