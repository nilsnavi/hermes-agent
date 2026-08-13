"""Provider health checks (Sprint 0.4 §6).

Low-cost strategy:
- preferred: metadata / models endpoint (GET)
- fallback for providers whose /models is not meaningful (e.g. claudehub
  serves a model list even with an invalid key): minimal inference probe
  (1 token) or an auth endpoint (/whoami).

TTL + jitter: a provider is re-probed only after its TTL expires; every
scheduled probe time gets ±jitter to avoid thundering herd. No background
loop is started implicitly — callers (tests / CLI / future gateway hook)
invoke run_probe_batch()/run_probe() explicitly. Nothing runs unless the
feature flag is enabled.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .classifier import ProviderErrorClassifier
from .domain import (
    AvailabilityReason,
    ProviderAuthStatus,
    ProviderHealthStatus,
    ProviderDefinition,
)
from .events import emit

# ── Probe specs ──────────────────────────────────────────────────────────
# kind:
#   models     — GET {base_url}{path} with Bearer key; 200 → healthy,
#                optionally captures model list.
#   inference  — minimal POST chat completion (max_tokens<=1) — used only
#                where /models is misleading (invalid-key providers still
#                serve a list). Fails fast with 401 → clean classification.
#   whoami     — auth-probe endpoint (Hugging Face).
#   none       — no live probe (static classification only; e.g. copilot
#                external-process auth, no credential env).

PROBE_SPECS: Dict[str, Dict[str, Any]] = {
    "opencode": {
        "kind": "models",
        "base_url": "https://opencode.ai/zen/v1",
        "path": "/models",
        "auth_var": "OPENCODE_ZEN_API_KEY",
        "auth": "bearer",
        "timeout_s": 8,
        "capture_models": True,
    },
    "deepseek": {
        "kind": "models",
        "base_url": "https://api.deepseek.com",
        "path": "/models",
        "auth_var": "DEEPSEEK_API_KEY",
        "auth": "bearer",
        "timeout_s": 8,
        "capture_models": True,
    },
    "openrouter": {
        "kind": "models",
        "base_url": "https://openrouter.ai/api/v1",
        "path": "/models",
        "auth_var": "OPENROUTER_API_KEY",
        "auth": "bearer",
        "timeout_s": 8,
    },
    "openai-api": {
        "kind": "models",
        "base_url": "https://api.openai.com/v1",
        "path": "/models",
        "auth_var": "OPENAI_API_KEY",
        "auth": "bearer",
        "timeout_s": 8,
    },
    "anthropic": {
        "kind": "models",
        "base_url": "https://api.anthropic.com/v1",
        "path": "/models",
        "auth_var": "ANTHROPIC_API_KEY",
        "auth": "x-api-key",
        "timeout_s": 8,
    },
    "google": {
        "kind": "models",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "path": "/models",  # ?key= via auth_query
        "auth_var": "GOOGLE_API_KEY",
        "auth": "query",
        "timeout_s": 8,
    },
    "huggingface": {
        "kind": "whoami",
        "base_url": "https://huggingface.co/api",
        "path": "/whoami",
        "auth_var": "HF_TOKEN",
        "auth": "bearer",
        "timeout_s": 8,
    },
    "nous": {
        "kind": "models",
        "base_url": "https://inference-api.nousresearch.com/v1",
        "path": "/models",
        "auth_var": "",          # OAuth token from auth.json (bootstrap injects)
        "auth": "bearer",
        "timeout_s": 8,
    },
    "github-copilot": {
        "kind": "models",
        "base_url": "https://api.githubcopilot.com",
        "path": "/v1/models",
        "auth_var": "GITHUB_TOKEN",
        "auth": "bearer",
        "timeout_s": 8,
    },
    # custom claudehub fallback — /models is meaningless here (serves list
    # with any key), so use a minimal inference probe that fails fast on 401.
    "claudehub": {
        "kind": "inference",
        "base_url": "https://api.claudehub.fun/v1",
        "path": "/chat/completions",
        "auth": "bearer",
        "timeout_s": 8,
        "body_model": "claude-sonnet-4.6",
    },
    "codex.sale": {
        "kind": "models",
        "base_url": "https://codex.sale/v1",
        "path": "/models",
        "auth": "bearer",
        "timeout_s": 8,
    },
    "agentrouter": {
        "kind": "models",
        "base_url": "https://agentrouter.org/v1",
        "path": "/models",
        "auth": "bearer",
        "timeout_s": 8,
    },
}


# ── TTL defaults (seconds) — configurable ────────────────────────────────

HEALTH_TTL_DEFAULTS = {
    "healthy": 600,      # 5–15 min window
    "degraded": 180,     # 2–5 min
    "unavailable": 1800, # 15–60 min
}
HEALTH_JITTER_FRACTION = 0.10  # ±10%


def _ttl_for(definition: ProviderDefinition, ttl_map: Dict[str, int]) -> int:
    if definition.healthStatus in (ProviderHealthStatus.UNAVAILABLE, ProviderHealthStatus.DISABLED):
        return ttl_map["unavailable"]
    if definition.healthStatus == ProviderHealthStatus.DEGRADED:
        return ttl_map["degraded"]
    if definition.healthStatus == ProviderHealthStatus.HEALTHY:
        return ttl_map["healthy"]
    return ttl_map["degraded"]


def _jitter(ttl: int, fraction: float, rng: random.Random) -> int:
    span = max(1, int(ttl * fraction))
    return ttl + rng.randint(-span, span)


class ProbeResult:
    """Outcome of one health probe (no secrets)."""

    def __init__(
        self,
        provider: str,
        ok: bool,
        http_status: Optional[int] = None,
        message: str = "",
        error_class: str = "",
        duration_ms: float = 0.0,
        models: Optional[List[str]] = None,
    ) -> None:
        self.provider = provider
        self.ok = ok
        self.http_status = http_status
        self.message = message
        self.error_class = error_class
        self.duration_ms = duration_ms
        self.models = models or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "ok": self.ok,
            "httpStatus": self.http_status,
            "errorClass": self.error_class,
            "durationMs": round(self.duration_ms, 1),
            "modelsCaptured": len(self.models),
        }


def _build_request(spec: Dict[str, Any], key: str) -> urllib.request.Request:
    """Build the probe request. ``key`` is the resolved credential value
    (may be empty — e.g. OpenRouter still returns its WAF 403 without it)."""
    base = spec["base_url"].rstrip("/")
    path = spec["path"].lstrip("/")
    url = f"{base}/{path}"
    headers = {"User-Agent": "hermes-provider-registry/0.4"}
    data = None
    if spec.get("kind") == "inference":
        body = {
            "model": spec.get("body_model", "claude-sonnet-4.6"),
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    auth_mode = spec.get("auth", "bearer")
    if auth_mode == "bearer" and key:
        headers["Authorization"] = f"Bearer {key}"
    elif auth_mode == "x-api-key" and key:
        headers["x-api-key"] = key
    elif auth_mode == "query" and key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={key}"
    return urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")


class HealthChecker:
    """Executes low-cost probes and folds results into the registry."""

    def __init__(
        self,
        registry,
        classifier: Optional[ProviderErrorClassifier] = None,
        ttl_map: Optional[Dict[str, int]] = None,
        jitter_fraction: float = HEALTH_JITTER_FRACTION,
        rng: Optional[random.Random] = None,
        env: Optional[Dict[str, str]] = None,
        credentials: Optional[Dict[str, str]] = None,
        probe_specs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.registry = registry
        self.classifier = classifier or ProviderErrorClassifier()
        self.ttl_map = dict(HEALTH_TTL_DEFAULTS)
        if ttl_map:
            self.ttl_map.update(ttl_map)
        self.jitter_fraction = jitter_fraction
        self.rng = rng or random.Random()
        self.env = env if env is not None else os.environ
        #: provider_id → auth value (bootstrap injects; never logged)
        self.credentials = dict(credentials or {})
        self.probe_specs = dict(probe_specs or PROBE_SPECS)

    # ── API ──────────────────────────────────────────────────────────────

    def due(self, definition: ProviderDefinition) -> bool:
        """True if a probe is due for this provider (TTL + jitter)."""
        if definition.healthCheckedAt is None:
            return True
        ttl = _ttl_for(definition, self.ttl_map)
        ttl_j = _jitter(ttl, self.jitter_fraction, self.rng)
        return (time.time() - definition.healthCheckedAt) >= ttl_j

    def run_probe(self, definition: ProviderDefinition) -> bool:
        """Probe one provider; update registry state. Returns ok."""
        spec = self.probe_specs.get(definition.id)
        if spec is None or spec.get("kind") == "none":
            return False
        if not self.due(definition):
            return definition.healthStatus == ProviderHealthStatus.HEALTHY
        emit("provider.health.started", provider=definition.id, status="started")
        result = self._probe_one(definition, spec)
        self._apply(definition, result)
        return result.ok

    def run_probe_batch(self, provider_ids: Optional[List[str]] = None) -> Dict[str, ProbeResult]:
        """Sequential one-shot batch (no thundering herd), returns results keyed by id."""
        ids = provider_ids or [d.id for d in self.registry.list_providers()]
        results: Dict[str, ProbeResult] = {}
        for pid in ids:
            d = self.registry.get_provider(pid)
            if d is None:
                continue
            spec = self.probe_specs.get(pid)
            if spec is None or spec.get("kind") == "none":
                continue
            results[pid] = self._probe_one(d, spec)
            self._apply(d, results[pid])
        return results

    # ── internals ─────────────────────────────────────────────────────────

    def _auth_value(self, definition: ProviderDefinition) -> str:
        if definition.id in self.credentials:
            return self.credentials[definition.id]
        spec = self.probe_specs.get(definition.id) or {}
        var = spec.get("auth_var", "")
        if var:
            return (self.env or os.environ).get(var, "")
        return ""

    def _probe_one(self, definition: ProviderDefinition, spec: Dict[str, Any]) -> ProbeResult:
        started = time.monotonic()
        key = self._auth_value(definition)
        try:
            req = _build_request(spec, key)
            with urllib.request.urlopen(req, timeout=spec.get("timeout_s", 8)) as resp:
                body = resp.read(200_000).decode("utf-8", "replace")
                dur_ms = (time.monotonic() - started) * 1000.0
                if resp.status == 200:
                    models = []
                    if spec.get("capture_models"):
                        models = self._extract_models(body)
                    return ProbeResult(definition.id, True, resp.status, "", "NONE", dur_ms, models)
                return ProbeResult(definition.id, False, resp.status, body[:400], "HTTP", dur_ms)
        except urllib.error.HTTPError as e:
            body = e.read(200_000).decode("utf-8", "replace")
            dur_ms = (time.monotonic() - started) * 1000.0
            return ProbeResult(definition.id, False, e.code, body[:400], "", dur_ms)
        except urllib.error.URLError as e:
            dur_ms = (time.monotonic() - started) * 1000.0
            return ProbeResult(definition.id, False, None, str(e.reason), "", dur_ms)
        except Exception as e:  # timeout etc.
            dur_ms = (time.monotonic() - started) * 1000.0
            return ProbeResult(definition.id, False, None, str(e), "", dur_ms)

    @staticmethod
    def _extract_models(body: str) -> List[str]:
        try:
            data = json.loads(body)
            out = []
            for item in data.get("data", []):
                mid = item.get("id")
                if mid:
                    out.append(str(mid))
            return out[:200]
        except Exception:
            return []

    def _apply(self, definition: ProviderDefinition, result: ProbeResult) -> None:
        """Fold probe result into registry state."""
        reg = self.registry
        if result.ok:
            reg.record_success(definition.id, http_status=result.http_status, duration_ms=result.duration_ms)
            if result.models:
                reg.update_models(definition.id, tuple(result.models))
            return
        cls = self.classifier.classify(
            provider=definition.id,
            http_status=result.http_status,
            message=result.message,
            error_type="",
            operation="health_probe",
        )
        reg.record_failure(
            definition.id,
            classification=cls,
            http_status=result.http_status,
            duration_ms=result.duration_ms,
            source="health_probe",
        )