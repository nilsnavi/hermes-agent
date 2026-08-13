"""Initial provider classification bootstrap (Sprint 0.4 §4).

Builds ProviderDefinitions from the current Hermes state without
disclosing any secret material:

- primary/fallback from config.yaml (model.provider / fallback_providers /
  custom_providers)
- credentialConfigured from .env key PRESENCE (names only) and auth.json
  structure (no values)
- initial health/auth/availability from the verified Sprint 0.3 findings —
  bootstrap only; health checks overwrite these afterwards

Secrets stay in .env / auth.json / config.yaml. This module reads names,
booleans and — for live probes only — resolves credentials into the
HealthChecker's in-memory map (never logged, never printed).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .domain import (
    AvailabilityReason,
    ProviderAuthStatus,
    ProviderDefinition,
    ProviderHealthStatus,
)

# ── Sprint 0.3 verified initial state (bootstrap only) ──────────────────

INITIAL_STATE: Dict[str, Dict[str, Any]] = {
    "opencode": dict(health=ProviderHealthStatus.HEALTHY, auth=ProviderAuthStatus.VALID,
                     reason=AvailabilityReason.NONE, eligible=True, display="OpenCode Zen"),
    "deepseek": dict(health=ProviderHealthStatus.DEGRADED, auth=ProviderAuthStatus.VALID,
                     reason=AvailabilityReason.NONE, eligible=True, display="DeepSeek"),
    "openrouter": dict(health=ProviderHealthStatus.UNAVAILABLE, auth=ProviderAuthStatus.VALID,
                       reason=AvailabilityReason.WAF_BLOCKED, eligible=False, display="OpenRouter"),
    "openai-api": dict(health=ProviderHealthStatus.UNAVAILABLE, auth=ProviderAuthStatus.UNKNOWN,
                       reason=AvailabilityReason.GEO_BLOCKED, eligible=False, display="OpenAI"),
    "anthropic": dict(health=ProviderHealthStatus.UNAVAILABLE, auth=ProviderAuthStatus.INVALID,
                      reason=AvailabilityReason.GEO_BLOCKED, eligible=False, display="Anthropic"),
    "google": dict(health=ProviderHealthStatus.UNAVAILABLE, auth=ProviderAuthStatus.UNKNOWN,
                   reason=AvailabilityReason.GEO_BLOCKED, eligible=False, display="Google Gemini"),
    "huggingface": dict(health=ProviderHealthStatus.UNAVAILABLE, auth=ProviderAuthStatus.INVALID,
                        reason=AvailabilityReason.AUTH, eligible=False, display="Hugging Face"),
    "github-copilot": dict(health=ProviderHealthStatus.UNAVAILABLE, auth=ProviderAuthStatus.UNSUPPORTED,
                           reason=AvailabilityReason.UNSUPPORTED_AUTH, eligible=False, display="GitHub Copilot"),
    "nous": dict(health=ProviderHealthStatus.UNAVAILABLE, auth=ProviderAuthStatus.EXPIRED,
                 reason=AvailabilityReason.MANUAL_REAUTH, eligible=False, display="Nous Portal"),
    "claudehub": dict(health=ProviderHealthStatus.UNAVAILABLE, auth=ProviderAuthStatus.INVALID,
                      reason=AvailabilityReason.AUTH, eligible=False, display="ClaudeHub (custom)"),
    "codex.sale": dict(health=ProviderHealthStatus.UNAVAILABLE, auth=ProviderAuthStatus.INVALID,
                       reason=AvailabilityReason.AUTH, eligible=False, display="Codex.sale (custom)"),
    "agentrouter": dict(health=ProviderHealthStatus.UNAVAILABLE, auth=ProviderAuthStatus.INVALID,
                        reason=AvailabilityReason.AUTH, eligible=False, display="AgentRouter (custom)"),
}

# Provider id → environment variable names that hold its credential (names only)
_CREDENTIAL_VARS: Dict[str, List[str]] = {
    "opencode": ["OPENCODE_ZEN_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "openai-api": ["OPENAI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN"],
    "google": ["GOOGLE_API_KEY"],
    "huggingface": ["HF_TOKEN"],
    "github-copilot": ["GITHUB_TOKEN"],
    "nous": [],
    "claudehub": [],
    "codex.sale": [],
    "agentrouter": [],
}

_KNOWN_DEFAULT_MODELS: Dict[str, str] = {
    "deepseek": "deepseek-chat",
    "opencode": "",
    "openrouter": "",
    "openai-api": "",
    "anthropic": "",
    "google": "",
    "huggingface": "",
    "github-copilot": "",
    "nous": "",
    "claudehub": "claude-sonnet-4.6",
}

# Host → canonical registry id for custom config entries
_CUSTOM_BY_HOST: List[Tuple[str, str]] = [
    ("api.claudehub.fun", "claudehub"),
    ("codex.sale", "codex.sale"),
    ("agentrouter.org", "agentrouter"),
    ("cloudflare", "cloudflare"),
    ("trycloudflare", "trycloudflare"),
]

#: counters route every fallback entry to the same canonical id
_FALLBACK_BASE_PRIORITY = {"claudehub": 10, "deepseek": 20}


# ── Config / env readers (no secrets) ────────────────────────────────────

def load_env(env_path: Optional[str] = None) -> Dict[str, str]:
    """Parse a .env file into a dict (names preserved, values opaque)."""
    path = Path(env_path or os.path.expanduser("~/.hermes/.env"))
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """config.yaml → dict. Uses yaml if available, else a minimal parser."""
    path = Path(config_path or os.path.expanduser("~/.hermes/config.yaml"))
    if not path.exists():
        return {}
    text = path.read_text(errors="ignore")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return _minimal_yaml(text)


def _minimal_yaml(text: str) -> Dict[str, Any]:
    """Fallback: extract just model / fallback_providers / custom_providers."""
    cfg: Dict[str, Any] = {"model": {}, "fallback_providers": [], "custom_providers": []}
    section = None
    current = None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.endswith(":") and not s.startswith("-") and " " not in s.rstrip(":"):
            section = s[:-1]
            if section in ("model",):
                current = {}
                cfg["model"] = current
            elif section in ("fallback_providers", "custom_providers"):
                current = None
                continue
            else:
                current = None
            continue
        if section == "model" and current is not None and ":" in s:
            k, _, v = s.partition(":")
            current[k.strip()] = v.strip()
    return cfg


def auth_json_shape(path: Optional[str] = None) -> Dict[str, Any]:
    """auth.json STRUCTURE ONLY — booleans and counts, no values."""
    p = Path(path or os.path.expanduser("~/.hermes/auth.json"))
    shape: Dict[str, Any] = {"has_nous_oauth": False, "credential_pool_count": 0}
    if not p.exists():
        return shape
    try:
        data = json.loads(p.read_text(errors="ignore"))
    except Exception:
        return shape
    shape["has_nous_oauth"] = isinstance(data.get("nous"), dict)
    shape["credential_pool_count"] = len(data.get("credential_pool") or {})
    return shape


def _custom_ids(config: Dict[str, Any]) -> Dict[str, str]:
    """canonical id → (display, default_model) from config custom/fallback entries."""
    out: Dict[str, str] = {}
    seen_prio: Dict[str, int] = {}
    for key in ("fallback_providers", "custom_providers"):
        for entry in config.get(key) or []:
            if not isinstance(entry, dict):
                continue
            base = str(entry.get("base_url") or "").lower()
            cid = _canonical_id_by_host(base)
            if not cid or cid not in INITIAL_STATE:
                continue
            out.setdefault(cid, str(entry.get("model") or ""))
            if cid not in seen_prio:
                seen_prio[cid] = len(out)
    return out


def _canonical_id_by_host(base_url: str) -> str:
    for host, cid in _CUSTOM_BY_HOST:
        if host in base_url:
            return cid
    return ""


def _primary_id(config: Dict[str, Any]) -> str:
    m = config.get("model") or {}
    return str(m.get("provider", ""))


def _primary_model(config: Dict[str, Any]) -> str:
    m = config.get("model") or {}
    return str(m.get("default", ""))


def _profiles_for(cid: str, model: str) -> Tuple[str, ...]:
    """INTERFACE-ONLY profile heuristic (real profiles = Sprint 0.5)."""
    profiles = {"BALANCED"}
    low = model.lower()
    if any(t in low for t in ("flash", "fast", "mini", "lite", "-quick")):
        profiles.add("FAST")
    if any(t in low for t in ("reason", "think", "r1", "o1", "o3", "pro")):
        profiles.add("REASONING")
    if any(t in low for t in ("code", "coder", "claude-sonnet", "engineering")):
        profiles.add("CODING")
    return tuple(sorted(profiles))


def _auth_type(cid: str) -> str:
    return {
        "nous": "oauth_device_code",
        "github-copilot": "external_process",
        "openai-api": "api_key",
        "anthropic": "api_key",
    }.get(cid, "api_key")


# ── Bootstrap ────────────────────────────────────────────────────────────

def build_registry(
    registry,
    config: Optional[Dict[str, Any]] = None,
    env: Optional[Dict[str, str]] = None,
    auth_path: Optional[str] = None,
    credentials_out: Optional[Dict[str, str]] = None,
) -> List[str]:
    """Populate a ProviderRegistry from current Hermes state.

    Returns the list of provider ids registered (baseline table order).
    ``credentials_out``: optional dict to receive {provider_id: credential}
    for HealthChecker — in-memory only, never logged or printed.
    """
    config = config if config is not None else load_config()
    env = env if env is not None else load_env()
    auth_shape = auth_json_shape(auth_path)

    primary_id = _primary_id(config)
    primary_model = _primary_model(config)
    custom_models = _custom_providers(config)

    # configured ids: primary + any custom entries found in config
    configured: set = set()
    if primary_id:
        configured.add(primary_id)
    for cid in custom_models:
        configured.add(cid)

    # baseline: all known providers (complete table), claudehub etc. only if
    # configured OR always for the known list:
    all_ids = list(INITIAL_STATE.keys())

    for cid in all_ids:
        info = INITIAL_STATE[cid]
        credential_configured = any(env.get(v) for v in _CREDENTIAL_VARS.get(cid, []))
        if cid == "nous" and auth_shape.get("has_nous_oauth"):
            credential_configured = True
        if not credential_configured and cid in custom_models:
            # custom entries carry their key inside config (fallback/custom_providers)
            credential_configured = _config_credential(cid, config)

        if cid == "opencode":
            default_model = primary_model or ""
        elif cid in custom_models:
            default_model = custom_models[cid] or _KNOWN_DEFAULT_MODELS.get(cid, "")
        else:
            default_model = _KNOWN_DEFAULT_MODELS.get(cid, "")

        fallback_prio = None
        if cid != primary_id and cid in _FALLBACK_BASE_PRIORITY:
            fallback_prio = _FALLBACK_BASE_PRIORITY[cid]

        definition = ProviderDefinition(
            id=cid,
            displayName=info["display"],
            enabled=True,
            authType=_auth_type(cid),
            credentialConfigured=credential_configured,
            defaultModel=default_model,
            supportedModelProfiles=_profiles_for(cid, default_model),
            priority=1 if cid == primary_id else 100,
            fallbackPriority=fallback_prio,
            metadata={"bootstrap": "sprint-0.4", "primary": cid == primary_id},
        )
        registry.register_provider(
            definition,
            initial_health=info["health"],
            initial_auth=info["auth"],
            initial_reason=info["reason"],
            initial_eligible=info["eligible"],
        )

        # credential for health probes (memory only — never logged)
        if credentials_out is not None:
            cred = _credential_for(cid, env, config, custom_models)
            if cred:
                credentials_out[cid] = cred

    return [p.id for p in registry.list_providers()]


def _config_credential(cid: str, config: Dict[str, Any]) -> bool:
    """True if a config entry (fallback/custom) for cid carries an api_key."""
    for key in ("fallback_providers", "custom_providers"):
        for entry in config.get(key, []) or []:
            host = (entry.get("base_url") or "").replace("https://", "").replace("http://", "").split("/")[0]
            if any(host == h and cid == c for h, c in _CUSTOM_BY_HOST):
                if entry.get("api_key"):
                    return True
    return False


def _credential_for(cid: str, env: Dict[str, str], config: Dict[str, Any], custom_models: Dict[str, str]) -> str:
    """Resolve the actual credential VALUE for live probes (memory only)."""
    if cid in ("claudehub", "codex.sale", "agentrouter"):
        # custom entries carry their key inside config
        for key in ("fallback_providers", "custom_providers"):
            for entry in config.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                if _canonical_id_by_host(str(entry.get("base_url") or "").lower()) == cid:
                    val = str(entry.get("api_key") or "")
                    if val:
                        return val
        return ""
    for var in _CREDENTIAL_VARS.get(cid, []):
        val = env.get(var, "")
        if val:
            return val
    return ""


def _custom_providers(config: Dict[str, Any]) -> Dict[str, str]:
    """canonical id → default model for custom/fallback config entries."""
    out: Dict[str, str] = {}
    for key in ("fallback_providers", "custom_providers"):
        for entry in config.get(key) or []:
            if not isinstance(entry, dict):
                continue
            base = str(entry.get("base_url") or "").lower()
            cid = _canonical_id_by_host(base)
            if cid:
                out.setdefault(cid, str(entry.get("model") or ""))
    return out