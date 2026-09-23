"""Model catalog reconciliation and reference inspection.

Phase 1 is intentionally read-only:
- locate active model references in config/profile files
- locate runtime gateway model overrides
- do not mutate configuration or historical sessions
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ModelReference:
    source: str
    location: str
    model: str
    mutable: bool
    kind: str


def _walk_model_refs(
    value: Any,
    model_id: str,
    path: str = "",
) -> Iterable[tuple[str, str]]:
    """Yield config paths that actively reference model_id.

    Catalog membership under custom_providers[*].models is intentionally
    excluded: catalog entries are availability data, not active routing refs.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)

            # Provider catalog itself is not an active reference.
            if key == "models" and "custom_providers" in path:
                continue

            if isinstance(child, str) and child == model_id:
                if key in {
                    "model",
                    "default",
                    "fallback_model",
                    "vision_model",
                    "reasoning_model",
                }:
                    yield child_path, "config"

            yield from _walk_model_refs(child, model_id, child_path)

    elif isinstance(value, list):
        for idx, child in enumerate(value):
            child_path = f"{path}[{idx}]"
            yield from _walk_model_refs(child, model_id, child_path)


def _scan_yaml(
    path: Path,
    model_id: str,
    source_label: str,
) -> list[ModelReference]:
    if not path.exists():
        return []

    import yaml

    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []

    refs: list[ModelReference] = []

    for location, kind in _walk_model_refs(cfg, model_id):
        refs.append(
            ModelReference(
                source=source_label,
                location=location,
                model=model_id,
                mutable=True,
                kind=kind,
            )
        )

    return refs


def _scan_gateway_routing(
    db_path: Path,
    model_id: str,
) -> list[ModelReference]:
    if not db_path.exists():
        return []

    refs: list[ModelReference] = []

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    try:
        rows = con.execute("""
            SELECT scope, session_key, entry_json
            FROM gateway_routing
        """).fetchall()

        for row in rows:
            try:
                entry = json.loads(row["entry_json"] or "{}")
            except Exception:
                continue

            override = entry.get("model_override") or {}
            if not isinstance(override, dict):
                continue

            if override.get("model") == model_id:
                refs.append(
                    ModelReference(
                        source="state.db",
                        location=(
                            "gateway_routing:"
                            f"{row['session_key']}.model_override.model"
                        ),
                        model=model_id,
                        mutable=True,
                        kind="runtime_override",
                    )
                )
    finally:
        con.close()

    return refs


def _scan_active_sessions(
    db_path: Path,
    model_id: str,
) -> list[ModelReference]:
    """Report active session usage.

    Session history is audit data and must never be rewritten by repair.
    """
    if not db_path.exists():
        return []

    refs: list[ModelReference] = []

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    try:
        rows = con.execute("""
            SELECT id, session_key, model
            FROM sessions
            WHERE ended_at IS NULL
              AND model = ?
        """, (model_id,)).fetchall()

        for row in rows:
            refs.append(
                ModelReference(
                    source="state.db",
                    location=f"sessions:{row['id']}",
                    model=model_id,
                    mutable=False,
                    kind="active_session_audit",
                )
            )
    finally:
        con.close()

    return refs


def scan_model_references(
    model_id: str,
    hermes_home: Path | None = None,
) -> list[ModelReference]:
    home = hermes_home or (Path.home() / ".hermes")

    refs: list[ModelReference] = []

    refs.extend(
        _scan_yaml(
            home / "config.yaml",
            model_id,
            "config.yaml",
        )
    )

    profiles = home / "profiles"
    if profiles.exists():
        for config in sorted(profiles.glob("*/config.yaml")):
            refs.extend(
                _scan_yaml(
                    config,
                    model_id,
                    str(config.relative_to(home)),
                )
            )

    state_db = home / "state.db"

    refs.extend(_scan_gateway_routing(state_db, model_id))
    refs.extend(_scan_active_sessions(state_db, model_id))

    return refs


def format_reference_report(
    model_id: str,
    refs: list[ModelReference],
) -> str:
    lines = [
        f"MODEL={model_id}",
        f"REFERENCES={len(refs)}",
    ]

    for ref in refs:
        state = "MUTABLE" if ref.mutable else "AUDIT_ONLY"
        lines.append(
            f"{state} | {ref.kind} | "
            f"{ref.source} | {ref.location}"
        )

    return "\n".join(lines)


def references_as_dicts(
    refs: list[ModelReference],
) -> list[dict[str, Any]]:
    return [asdict(ref) for ref in refs]


def get_anymodel_catalog(
    hermes_home: Path | None = None,
) -> list[str]:
    """Return the locally persisted live-discovered AnyModel catalog."""
    import yaml

    home = hermes_home or (Path.home() / ".hermes")
    cfg_path = home / "config.yaml"

    cfg = yaml.safe_load(
        cfg_path.read_text(encoding="utf-8")
    ) or {}

    for entry in cfg.get("custom_providers", []):
        if not isinstance(entry, dict):
            continue

        if entry.get("name") != "AnyModel":
            continue

        models = entry.get("models", {})

        if isinstance(models, dict):
            return [
                str(m)
                for m in models
                if not str(m).startswith("__")
            ]

        if isinstance(models, list):
            out = []

            for item in models:
                if isinstance(item, str):
                    out.append(item)

                elif isinstance(item, dict):
                    mid = item.get("id") or item.get("model")
                    if mid:
                        out.append(str(mid))

            return out

    return []


def _model_family(model_id: str) -> str:
    """Best-effort family used only for candidate ordering.

    More specific families must appear before overlapping generic names.
    """
    value = model_id.lower()

    for family in (
        "nemotron",
        "mistral",
        "grok",
        "gemini",
        "claude",
        "deepseek",
        "qwen",
        "glm",
        "kimi",
        "gpt",
    ):
        if family in value:
            return family

    return ""


def suggest_replacements(
    model_id: str,
    hermes_home: Path | None = None,
    limit: int = 10,
) -> list[str]:
    """Return deterministic replacement candidates.

    Phase 1 performs conservative family/provider ordering only.
    Capability filtering is added in the next phase.
    """
    catalog = get_anymodel_catalog(hermes_home)

    candidates = [
        model
        for model in catalog
        if model != model_id
        and model_allowed_as_replacement(
            model,
            hermes_home,
        )
    ]

    family = _model_family(model_id)
    prefix = model_id.split("/", 1)[0] if "/" in model_id else ""

    def score(candidate: str):
        candidate_family = _model_family(candidate)
        candidate_prefix = (
            candidate.split("/", 1)[0]
            if "/" in candidate
            else ""
        )

        return (
            0 if family and candidate_family == family else 1,
            0 if prefix and candidate_prefix == prefix else 1,
            candidate,
        )

    return sorted(candidates, key=score)[:limit]


def build_replacement_plan(
    model_id: str,
    hermes_home: Path | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    refs = scan_model_references(model_id, hermes_home)
    suggestions = suggest_replacements(
        model_id,
        hermes_home,
        limit=limit,
    )

    mutable = [r for r in refs if r.mutable]
    audit = [r for r in refs if not r.mutable]

    return {
        "model": model_id,
        "mutable_references": references_as_dicts(mutable),
        "audit_references": references_as_dicts(audit),
        "suggestions": suggestions,
    }


def format_replacement_plan(plan: dict[str, Any]) -> str:
    lines = [
        f"BROKEN_MODEL={plan['model']}",
        f"MUTABLE_REFERENCES={len(plan['mutable_references'])}",
        f"AUDIT_REFERENCES={len(plan['audit_references'])}",
        "",
        "MUTABLE:",
    ]

    for ref in plan["mutable_references"]:
        lines.append(
            f"  - {ref['source']} | {ref['location']}"
        )

    lines.append("")
    lines.append("SUGGESTED_REPLACEMENTS:")

    for idx, model in enumerate(plan["suggestions"], 1):
        lines.append(f"  {idx}. {model}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Model health registry
# ---------------------------------------------------------------------------

from datetime import datetime, timezone


HEALTHY = "healthy"
UNKNOWN = "unknown"
SUSPECT = "suspect"
COOLDOWN = "cooldown"
QUARANTINED = "quarantined"
RETIRED = "retired"

_BLOCKED_REPLACEMENT_STATES = {
    QUARANTINED,
    RETIRED,
}


def _health_path(
    hermes_home: Path | None = None,
) -> Path:
    home = hermes_home or (Path.home() / ".hermes")
    return home / "model_health.json"


def load_model_health(
    hermes_home: Path | None = None,
) -> dict[str, Any]:
    path = _health_path(hermes_home)

    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def save_model_health(
    data: dict[str, Any],
    hermes_home: Path | None = None,
) -> None:
    path = _health_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(".json.tmp")

    tmp.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    tmp.chmod(0o600)
    tmp.replace(path)
    path.chmod(0o600)


def set_model_health(
    model_id: str,
    state: str,
    *,
    reason: str = "",
    error: str = "",
    hermes_home: Path | None = None,
) -> dict[str, Any]:

    allowed = {
        HEALTHY,
        UNKNOWN,
        SUSPECT,
        COOLDOWN,
        QUARANTINED,
        RETIRED,
    }

    if state not in allowed:
        raise ValueError(f"Invalid model health state: {state}")

    health = load_model_health(hermes_home)

    now = datetime.now(timezone.utc).isoformat()

    previous = health.get(model_id, {})
    count = int(previous.get("failure_count", 0))

    if state in {
        SUSPECT,
        COOLDOWN,
        QUARANTINED,
        RETIRED,
    }:
        count += 1

    record = {
        **previous,
        "state": state,
        "reason": reason,
        "last_updated_at": now,
        "failure_count": count,
    }

    if error:
        record["last_error"] = error

    if (
        state in {SUSPECT, COOLDOWN, QUARANTINED, RETIRED}
        and "first_failed_at" not in record
    ):
        record["first_failed_at"] = now

    if state in {SUSPECT, COOLDOWN, QUARANTINED, RETIRED}:
        record["last_failed_at"] = now

    health[model_id] = record

    save_model_health(health, hermes_home)

    return record


def model_health_state(
    model_id: str,
    hermes_home: Path | None = None,
) -> str:
    health = load_model_health(hermes_home)

    record = health.get(model_id)

    if not isinstance(record, dict):
        return UNKNOWN

    return str(record.get("state") or UNKNOWN)


def model_allowed_as_replacement(
    model_id: str,
    hermes_home: Path | None = None,
) -> bool:
    return (
        model_health_state(model_id, hermes_home)
        not in _BLOCKED_REPLACEMENT_STATES
    )


# ---------------------------------------------------------------------------
# Capability resolution
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapabilityIdentity:
    provider: str
    model: str
    source: str


def _bare_anymodel_id(model_id: str) -> str:
    return model_id.split("/", 1)[1] if "/" in model_id else model_id


def _preferred_registry_providers(model_id: str) -> list[str]:
    prefix = model_id.split("/", 1)[0].lower() if "/" in model_id else ""

    hints = {
        "xai": ["xai"],
        "cx": ["openai"],
        "am": ["nvidia"],
        "ds": ["deepseek"],
        "glm": ["zai"],
        "kmc": ["kimi-for-coding"],
    }

    return hints.get(prefix, [])


def _registry_model_match_score(
    candidate: str,
    bare: str,
) -> int | None:
    """Lower score is better."""

    c = candidate.lower()
    b = bare.lower()

    if c == b:
        return 0

    if c.endswith("/" + b):
        return 1

    # Covers ids such as nvidia/foo and mistralai/foo when AnyModel exposes
    # only the final model slug.
    if c.rsplit("/", 1)[-1] == b:
        return 2

    return None


def resolve_capability_identity(
    model_id: str,
    *,
    allow_network: bool = False,
) -> CapabilityIdentity | None:
    """Resolve an AnyModel-style id to a models.dev provider/model pair."""

    from agent.models_dev import fetch_models_dev

    registry = fetch_models_dev(
        force_refresh=False,
        allow_network=allow_network,
    )

    if not isinstance(registry, dict):
        return None

    bare = _bare_anymodel_id(model_id)
    preferred = _preferred_registry_providers(model_id)

    hits: list[tuple[int, int, str, str]] = []

    for provider_id, provider_data in registry.items():
        if not isinstance(provider_data, dict):
            continue

        models = provider_data.get("models") or {}

        if not isinstance(models, dict):
            continue

        provider_priority = (
            preferred.index(provider_id)
            if provider_id in preferred
            else 100
        )

        for registry_model in models:
            registry_model = str(registry_model)

            match_score = _registry_model_match_score(
                registry_model,
                bare,
            )

            if match_score is None:
                continue

            hits.append(
                (
                    provider_priority,
                    match_score,
                    str(provider_id),
                    registry_model,
                )
            )

    if not hits:
        return None

    hits.sort()

    _, _, provider, model = hits[0]

    return CapabilityIdentity(
        provider=provider,
        model=model,
        source="models.dev",
    )


@dataclass(frozen=True)
class ResolvedCapabilities:
    known: bool
    provider: str = ""
    model: str = ""
    supports_tools: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False
    context_window: int = 0
    model_family: str = ""
    source: str = ""


def resolve_model_capabilities(
    model_id: str,
    *,
    allow_network: bool = False,
) -> ResolvedCapabilities:
    from agent.models_dev import get_model_capabilities

    identity = resolve_capability_identity(
        model_id,
        allow_network=allow_network,
    )

    if identity is None:
        return ResolvedCapabilities(
            known=False,
            source="unresolved",
        )

    caps = get_model_capabilities(
        identity.provider,
        identity.model,
        allow_network=allow_network,
    )

    if caps is None:
        return ResolvedCapabilities(
            known=False,
            provider=identity.provider,
            model=identity.model,
            source=identity.source,
        )

    return ResolvedCapabilities(
        known=True,
        provider=identity.provider,
        model=identity.model,
        supports_tools=caps.supports_tools,
        supports_vision=caps.supports_vision,
        supports_reasoning=caps.supports_reasoning,
        context_window=caps.context_window,
        model_family=caps.model_family,
        source=identity.source,
    )


# ---------------------------------------------------------------------------
# Replacement role filtering
# ---------------------------------------------------------------------------

_NON_CHAT_PATTERNS = (
    "flux",
    "diffusion",
    "imagine-image",
    "image-generation",
    "image-preview",
    "content-safety",
    "moderation",
    "embedding",
    "rerank",
    "re-rank",
    "translate",
    "-tts",
    "speech",
    "whisper",
)


def is_general_chat_candidate(model_id: str) -> bool:
    value = model_id.lower()

    return not any(
        pattern in value
        for pattern in _NON_CHAT_PATTERNS
    )


@dataclass(frozen=True)
class ReplacementCandidate:
    model: str
    known: bool
    provider: str
    registry_model: str
    supports_tools: bool
    supports_vision: bool
    supports_reasoning: bool
    context_window: int
    family: str
    score: tuple


def _replacement_candidate(
    model_id: str,
    broken_model: str,
    hermes_home: Path | None = None,
) -> ReplacementCandidate | None:

    if model_id == broken_model:
        return None

    if not model_allowed_as_replacement(
        model_id,
        hermes_home,
    ):
        return None

    if not is_general_chat_candidate(model_id):
        return None

    caps = resolve_model_capabilities(
        model_id,
        allow_network=False,
    )

    requirements = replacement_requirements(
        broken_model,
    )

    if not capability_compatible(
        caps,
        requirements,
    ):
        return None

    broken_family = (
        requirements.family
        or _model_family(broken_model)
    )
    candidate_family = (
        caps.model_family.lower()
        if caps.known and caps.model_family
        else _model_family(model_id)
    )

    broken_prefix = (
        broken_model.split("/", 1)[0]
        if "/" in broken_model
        else ""
    )

    candidate_prefix = (
        model_id.split("/", 1)[0]
        if "/" in model_id
        else ""
    )

    score = (
        0 if caps.known else 1,
        0 if broken_family and candidate_family == broken_family else 1,
        0 if broken_prefix and candidate_prefix == broken_prefix else 1,
        0 if caps.known and caps.supports_tools else 1,
        0 if caps.known and caps.supports_reasoning else 1,
        -(caps.context_window if caps.known else 0),
        model_id,
    )

    return ReplacementCandidate(
        model=model_id,
        known=caps.known,
        provider=caps.provider,
        registry_model=caps.model,
        supports_tools=caps.supports_tools,
        supports_vision=caps.supports_vision,
        supports_reasoning=caps.supports_reasoning,
        context_window=caps.context_window,
        family=candidate_family,
        score=score,
    )


def suggest_capability_replacements(
    model_id: str,
    hermes_home: Path | None = None,
    *,
    limit: int = 12,
) -> list[ReplacementCandidate]:

    catalog = get_anymodel_catalog(hermes_home)

    candidates = []

    for candidate_id in catalog:
        candidate = _replacement_candidate(
            candidate_id,
            model_id,
            hermes_home,
        )

        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(key=lambda c: c.score)

    return candidates[:limit]


def format_capability_replacements(
    model_id: str,
    candidates: list[ReplacementCandidate],
) -> str:

    lines = [
        f"BROKEN_MODEL={model_id}",
        f"CANDIDATES={len(candidates)}",
        "",
    ]

    for idx, candidate in enumerate(candidates, 1):
        known = "KNOWN" if candidate.known else "UNKNOWN"

        lines.append(
            f"{idx}. {candidate.model} | "
            f"{known} | "
            f"provider={candidate.provider or '-'} | "
            f"tools={candidate.supports_tools} | "
            f"vision={candidate.supports_vision} | "
            f"reasoning={candidate.supports_reasoning} | "
            f"context={candidate.context_window or '-'} | "
            f"family={candidate.family or '-'}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Capability compatibility
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReplacementRequirements:
    known: bool
    supports_tools: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False
    min_context_window: int = 0
    family: str = ""


def replacement_requirements(
    model_id: str,
) -> ReplacementRequirements:
    caps = resolve_model_capabilities(
        model_id,
        allow_network=False,
    )

    if not caps.known:
        return ReplacementRequirements(
            known=False,
            family=_model_family(model_id),
        )

    return ReplacementRequirements(
        known=True,
        supports_tools=caps.supports_tools,
        supports_vision=caps.supports_vision,
        supports_reasoning=caps.supports_reasoning,
        min_context_window=caps.context_window,
        family=caps.model_family or _model_family(model_id),
    )


def capability_compatible(
    candidate: ResolvedCapabilities,
    requirements: ReplacementRequirements,
) -> bool:
    """True only when a candidate preserves required capabilities."""

    if not candidate.known:
        return False

    # If the broken model's capabilities are unresolved we cannot prove
    # compatibility, so it must not enter the automatic recommendation set.
    if not requirements.known:
        return False

    if requirements.supports_tools and not candidate.supports_tools:
        return False

    if requirements.supports_vision and not candidate.supports_vision:
        return False

    if requirements.supports_reasoning and not candidate.supports_reasoning:
        return False

    if (
        requirements.min_context_window
        and candidate.context_window < requirements.min_context_window
    ):
        return False

    return True


# ---------------------------------------------------------------------------
# Transactional replacement planning
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReplacementPlan:
    old_model: str
    new_model: str
    mutable_references: tuple[ModelReference, ...]
    audit_references: tuple[ModelReference, ...]
    replacement_caps: ResolvedCapabilities


def validate_replacement_target(
    old_model: str,
    new_model: str,
    hermes_home: Path | None = None,
) -> ResolvedCapabilities:
    catalog = set(get_anymodel_catalog(hermes_home))

    if new_model not in catalog:
        raise ValueError(
            f"Replacement model is not in live AnyModel catalog: {new_model}"
        )

    if not model_allowed_as_replacement(new_model, hermes_home):
        state = model_health_state(new_model, hermes_home)
        raise ValueError(
            f"Replacement model is blocked by health state: "
            f"{new_model} ({state})"
        )

    if not is_general_chat_candidate(new_model):
        raise ValueError(
            f"Replacement is not a general chat model: {new_model}"
        )

    requirements = replacement_requirements(old_model)

    if not requirements.known:
        raise ValueError(
            f"Cannot prove capabilities of source model: {old_model}"
        )

    caps = resolve_model_capabilities(
        new_model,
        allow_network=False,
    )

    if not capability_compatible(caps, requirements):
        raise ValueError(
            f"Replacement does not preserve required capabilities: "
            f"{old_model} -> {new_model}"
        )

    return caps


def build_transactional_replacement_plan(
    old_model: str,
    new_model: str,
    hermes_home: Path | None = None,
) -> ReplacementPlan:
    if old_model == new_model:
        raise ValueError("Old and new model are identical")

    caps = validate_replacement_target(
        old_model,
        new_model,
        hermes_home,
    )

    refs = scan_model_references(
        old_model,
        hermes_home,
    )

    mutable = tuple(
        ref for ref in refs
        if ref.mutable
    )

    audit = tuple(
        ref for ref in refs
        if not ref.mutable
    )

    if not mutable:
        raise ValueError(
            f"No mutable references found for {old_model}"
        )

    return ReplacementPlan(
        old_model=old_model,
        new_model=new_model,
        mutable_references=mutable,
        audit_references=audit,
        replacement_caps=caps,
    )


def format_transactional_plan(
    plan: ReplacementPlan,
) -> str:
    lines = [
        "MODEL_REPLACEMENT_PLAN",
        f"FROM={plan.old_model}",
        f"TO={plan.new_model}",
        f"MUTABLE={len(plan.mutable_references)}",
        f"AUDIT_ONLY={len(plan.audit_references)}",
        "",
        "CHANGES:",
    ]

    for ref in plan.mutable_references:
        lines.append(
            f"  - {ref.source} | {ref.location}"
        )

    if plan.audit_references:
        lines.extend([
            "",
            "PRESERVED_AUDIT_REFERENCES:",
        ])

        for ref in plan.audit_references:
            lines.append(
                f"  - {ref.source} | {ref.location}"
            )

    lines.extend([
        "",
        "REPLACEMENT_CAPABILITIES:",
        f"  provider={plan.replacement_caps.provider}",
        f"  tools={plan.replacement_caps.supports_tools}",
        f"  vision={plan.replacement_caps.supports_vision}",
        f"  reasoning={plan.replacement_caps.supports_reasoning}",
        f"  context={plan.replacement_caps.context_window}",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Transactional replacement application
# ---------------------------------------------------------------------------

import os
import shutil
import tempfile
import time


def _replace_model_values(
    value: Any,
    old_model: str,
    new_model: str,
    path: str = "",
) -> int:
    """Replace active config model references recursively.

    custom_providers[*].models is availability/catalog data and is never
    modified here.
    """
    changed = 0

    if isinstance(value, dict):
        for key, child in list(value.items()):
            child_path = f"{path}.{key}" if path else str(key)

            if key == "models" and "custom_providers" in path:
                continue

            if (
                isinstance(child, str)
                and child == old_model
                and key in {
                    "model",
                    "default",
                    "fallback_model",
                    "vision_model",
                    "reasoning_model",
                }
            ):
                value[key] = new_model
                changed += 1
                continue

            changed += _replace_model_values(
                child,
                old_model,
                new_model,
                child_path,
            )

    elif isinstance(value, list):
        for idx, child in enumerate(value):
            changed += _replace_model_values(
                child,
                old_model,
                new_model,
                f"{path}[{idx}]",
            )

    return changed


def _atomic_write_yaml(path: Path, data: Any) -> None:
    import yaml

    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600

    rendered = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
    )

    # Validate before replacing.
    check = yaml.safe_load(rendered)
    if check is None:
        raise ValueError(f"Rendered YAML is empty: {path}")

    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
        text=True,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(rendered)
            fh.flush()
            os.fsync(fh.fileno())

        os.chmod(tmp, mode)
        os.replace(tmp, path)

    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _replacement_backup_dir(
    hermes_home: Path,
) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")

    root = (
        hermes_home
        / "backups"
        / f"model-replacement-{stamp}"
    )

    root.mkdir(
        parents=True,
        exist_ok=False,
    )

    root.chmod(0o700)

    return root


def apply_model_replacement(
    old_model: str,
    new_model: str,
    *,
    hermes_home: Path | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Apply an approved model replacement transactionally.

    Historical/active session audit rows are intentionally untouched.
    """

    if not confirmed:
        raise PermissionError(
            "Replacement requires explicit confirmed=True"
        )

    home = hermes_home or (Path.home() / ".hermes")

    plan = build_transactional_replacement_plan(
        old_model,
        new_model,
        home,
    )

    backup_dir = _replacement_backup_dir(home)

    yaml_paths: list[Path] = []

    config_path = home / "config.yaml"
    if config_path.exists():
        yaml_paths.append(config_path)

    profiles_dir = home / "profiles"
    if profiles_dir.exists():
        yaml_paths.extend(
            sorted(profiles_dir.glob("*/config.yaml"))
        )

    # Back up YAML files.
    backed_up: dict[Path, Path] = {}

    for path in yaml_paths:
        relative = path.relative_to(home)
        dest = backup_dir / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        backed_up[path] = dest

    state_db = home / "state.db"
    db_backup = backup_dir / "state.db"

    conn: sqlite3.Connection | None = None
    yaml_change_count = 0
    routing_change_count = 0

    try:
        # SQLite online backup is safer than blindly copying a live DB.
        if state_db.exists():
            src = sqlite3.connect(
                f"file:{state_db}?mode=ro",
                uri=True,
            )
            dst = sqlite3.connect(str(db_backup))

            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()

            db_backup.chmod(0o600)

        import yaml

        # Prepare patched YAML completely in memory first.
        patched_yaml: dict[Path, Any] = {}

        for path in yaml_paths:
            data = yaml.safe_load(
                path.read_text(encoding="utf-8")
            ) or {}

            count = _replace_model_values(
                data,
                old_model,
                new_model,
            )

            if count:
                patched_yaml[path] = data
                yaml_change_count += count

        if state_db.exists():
            conn = sqlite3.connect(
                str(state_db),
                timeout=30,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")

            rows = conn.execute("""
                SELECT scope, session_key, entry_json
                FROM gateway_routing
            """).fetchall()

            for row in rows:
                try:
                    entry = json.loads(
                        row["entry_json"] or "{}"
                    )
                except Exception:
                    continue

                override = entry.get("model_override")

                if not isinstance(override, dict):
                    continue

                if override.get("model") != old_model:
                    continue

                override["model"] = new_model
                entry["model_override"] = override

                conn.execute("""
                    UPDATE gateway_routing
                    SET entry_json = ?
                    WHERE scope = ?
                      AND session_key = ?
                """, (
                    json.dumps(
                        entry,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    row["scope"],
                    row["session_key"],
                ))

                routing_change_count += 1

        # Only after all preparation succeeds, replace YAML files.
        for path, data in patched_yaml.items():
            _atomic_write_yaml(path, data)

        # Verify YAML no longer contains mutable old-model refs.
        remaining_yaml_refs: list[str] = []

        for path in yaml_paths:
            data = yaml.safe_load(
                path.read_text(encoding="utf-8")
            ) or {}

            for location, _ in _walk_model_refs(
                data,
                old_model,
            ):
                remaining_yaml_refs.append(
                    f"{path}:{location}"
                )

        if remaining_yaml_refs:
            raise RuntimeError(
                "Old model still has mutable YAML references: "
                + ", ".join(remaining_yaml_refs)
            )

        # Verify uncommitted routing state through this transaction.
        if conn is not None:
            rows = conn.execute("""
                SELECT scope, session_key, entry_json
                FROM gateway_routing
            """).fetchall()

            remaining_routes = []

            for row in rows:
                try:
                    entry = json.loads(
                        row["entry_json"] or "{}"
                    )
                except Exception:
                    continue

                override = entry.get("model_override") or {}

                if (
                    isinstance(override, dict)
                    and override.get("model") == old_model
                ):
                    remaining_routes.append(
                        row["session_key"]
                    )

            if remaining_routes:
                raise RuntimeError(
                    "Old model remains in gateway routing: "
                    + ", ".join(remaining_routes)
                )

            conn.commit()

        return {
            "status": "PASS",
            "old_model": old_model,
            "new_model": new_model,
            "yaml_changes": yaml_change_count,
            "routing_changes": routing_change_count,
            "audit_preserved": len(plan.audit_references),
            "backup_dir": str(backup_dir),
        }

    except Exception:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.rollback()

        # Restore YAML files from backups.
        for original, backup in backed_up.items():
            with contextlib.suppress(Exception):
                shutil.copy2(backup, original)

        raise

    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# Non-interactive catalog reconciliation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CatalogDiff:
    provider_name: str
    configured: tuple[str, ...]
    live: tuple[str, ...]
    added: tuple[str, ...]
    missing: tuple[str, ...]
    unchanged: tuple[str, ...]


def _get_custom_provider_entry(
    cfg: dict[str, Any],
    provider_name: str,
) -> dict[str, Any] | None:
    for entry in cfg.get("custom_providers", []):
        if (
            isinstance(entry, dict)
            and entry.get("name") == provider_name
        ):
            return entry

    return None


def _catalog_ids_from_entry(
    entry: dict[str, Any],
) -> list[str]:
    models = entry.get("models", {})

    if isinstance(models, dict):
        return [
            str(model_id)
            for model_id in models
            if not str(model_id).startswith("__")
        ]

    if isinstance(models, list):
        out: list[str] = []

        for item in models:
            if isinstance(item, str):
                out.append(item)

            elif isinstance(item, dict):
                model_id = item.get("id") or item.get("model")

                if model_id:
                    out.append(str(model_id))

        return out

    return []


def fetch_live_custom_provider_models(
    provider_name: str = "AnyModel",
    hermes_home: Path | None = None,
) -> list[str]:
    """Fetch live models without entering the interactive model picker."""
    import yaml

    from hermes_cli.config import normalize_extra_headers
    from hermes_cli.models import fetch_api_models

    home = hermes_home or (Path.home() / ".hermes")
    config_path = home / "config.yaml"

    cfg = yaml.safe_load(
        config_path.read_text(encoding="utf-8")
    ) or {}

    entry = _get_custom_provider_entry(
        cfg,
        provider_name,
    )

    if entry is None:
        raise ValueError(
            f"Custom provider not found: {provider_name}"
        )

    base_url = str(entry.get("base_url") or "").strip()

    if not base_url:
        raise ValueError(
            f"Provider has no base_url: {provider_name}"
        )

    api_mode = str(
        entry.get("api_mode") or ""
    ).strip()

    key_env = str(
        entry.get("key_env")
        or entry.get("api_key_env")
        or ""
    ).strip()

    from hermes_cli.config import get_env_value_prefer_dotenv

    api_key = (
        get_env_value_prefer_dotenv(key_env) or ""
        if key_env
        else ""
    )

    headers = (
        normalize_extra_headers(
            entry.get("extra_headers")
        )
        or {}
    )

    kwargs: dict[str, Any] = {
        "timeout": 8.0,
    }

    if api_mode:
        kwargs["api_mode"] = api_mode

    models = fetch_api_models(
        api_key,
        base_url,
        headers=headers or None,
        **kwargs,
    )

    if models is None:
        raise RuntimeError(
            f"Live model discovery failed for {provider_name}"
        )

    return [
        str(model_id)
        for model_id in models
        if str(model_id).strip()
    ]


def diff_custom_provider_catalog(
    provider_name: str = "AnyModel",
    hermes_home: Path | None = None,
) -> CatalogDiff:
    import yaml

    home = hermes_home or (Path.home() / ".hermes")
    config_path = home / "config.yaml"

    cfg = yaml.safe_load(
        config_path.read_text(encoding="utf-8")
    ) or {}

    entry = _get_custom_provider_entry(
        cfg,
        provider_name,
    )

    if entry is None:
        raise ValueError(
            f"Custom provider not found: {provider_name}"
        )

    configured = _catalog_ids_from_entry(entry)

    live = fetch_live_custom_provider_models(
        provider_name,
        home,
    )

    configured_set = set(configured)
    live_set = set(live)

    return CatalogDiff(
        provider_name=provider_name,
        configured=tuple(configured),
        live=tuple(live),
        added=tuple(
            model for model in live
            if model not in configured_set
        ),
        missing=tuple(
            model for model in configured
            if model not in live_set
        ),
        unchanged=tuple(
            model for model in live
            if model in configured_set
        ),
    )


def format_catalog_diff(
    diff: CatalogDiff,
) -> str:
    lines = [
        f"PROVIDER={diff.provider_name}",
        f"CONFIGURED={len(diff.configured)}",
        f"LIVE={len(diff.live)}",
        f"ADDED={len(diff.added)}",
        f"MISSING={len(diff.missing)}",
        f"UNCHANGED={len(diff.unchanged)}",
    ]

    if diff.added:
        lines.extend([
            "",
            "NEW:",
        ])

        for model in diff.added:
            lines.append(f"  + {model}")

    if diff.missing:
        lines.extend([
            "",
            "MISSING:",
        ])

        for model in diff.missing:
            lines.append(f"  - {model}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stateful catalog reconciliation policy
# ---------------------------------------------------------------------------

CATALOG_MISSING_MIN_CHECKS = 3
CATALOG_MISSING_MIN_AGE_SECONDS = 24 * 3600


@dataclass(frozen=True)
class CatalogReconcilePlan:
    provider_name: str
    live_count: int
    configured_count: int
    add: tuple[str, ...]
    keep_missing: tuple[str, ...]
    remove: tuple[str, ...]
    unchanged: tuple[str, ...]


def _reconcile_state_path(
    hermes_home: Path | None = None,
) -> Path:
    home = hermes_home or (Path.home() / ".hermes")
    return home / "model_reconcile_state.json"


def load_reconcile_state(
    hermes_home: Path | None = None,
) -> dict[str, Any]:
    path = _reconcile_state_path(hermes_home)

    if not path.exists():
        return {}

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def save_reconcile_state(
    state: dict[str, Any],
    hermes_home: Path | None = None,
) -> None:
    path = _reconcile_state_path(hermes_home)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = path.with_suffix(".json.tmp")

    tmp.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    tmp.chmod(0o600)
    tmp.replace(path)
    path.chmod(0o600)


def _parse_iso_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def build_catalog_reconcile_plan(
    provider_name: str = "AnyModel",
    hermes_home: Path | None = None,
    *,
    now: datetime | None = None,
) -> tuple[CatalogReconcilePlan, dict[str, Any]]:
    """Build reconciliation plan after one successful authoritative live probe.

    Important:
    - this function must only be called after a successful live /models fetch;
    - temporary provider/network failures must never advance missing counters.
    """
    home = hermes_home or (Path.home() / ".hermes")

    diff = diff_custom_provider_catalog(
        provider_name,
        home,
    )

    current_time = now or datetime.now(timezone.utc)

    state = load_reconcile_state(home)

    providers_state = state.setdefault(
        "providers",
        {},
    )

    provider_state = providers_state.setdefault(
        provider_name,
        {},
    )

    missing_state = provider_state.setdefault(
        "missing",
        {},
    )

    # Any model that is present again is no longer missing.
    live_set = set(diff.live)

    for model_id in list(missing_state):
        if model_id in live_set:
            missing_state.pop(model_id, None)

    keep_missing: list[str] = []
    remove: list[str] = []

    for model_id in diff.missing:
        record = missing_state.get(model_id)

        if not isinstance(record, dict):
            record = {
                "first_missing_at": current_time.isoformat(),
                "last_missing_at": current_time.isoformat(),
                "consecutive_successful_absences": 1,
            }
        else:
            record["last_missing_at"] = current_time.isoformat()
            record["consecutive_successful_absences"] = (
                int(
                    record.get(
                        "consecutive_successful_absences",
                        0,
                    )
                )
                + 1
            )

        missing_state[model_id] = record

        first_seen = _parse_iso_time(
            str(record.get("first_missing_at") or "")
        )

        age_seconds = (
            (current_time - first_seen).total_seconds()
            if first_seen is not None
            else 0
        )

        count = int(
            record.get(
                "consecutive_successful_absences",
                0,
            )
        )

        if (
            count >= CATALOG_MISSING_MIN_CHECKS
            and age_seconds
                >= CATALOG_MISSING_MIN_AGE_SECONDS
        ):
            remove.append(model_id)
        else:
            keep_missing.append(model_id)

    # Once a model has satisfied the removal policy, its missing
    # tracking record has served its purpose. Do not retain stale
    # reconciliation state indefinitely.
    for model_id in remove:
        missing_state.pop(model_id, None)

    provider_state["last_successful_sync_at"] = (
        current_time.isoformat()
    )

    provider_state["last_live_count"] = len(diff.live)

    plan = CatalogReconcilePlan(
        provider_name=provider_name,
        live_count=len(diff.live),
        configured_count=len(diff.configured),
        add=tuple(diff.added),
        keep_missing=tuple(keep_missing),
        remove=tuple(remove),
        unchanged=tuple(diff.unchanged),
    )

    return plan, state


def format_catalog_reconcile_plan(
    plan: CatalogReconcilePlan,
) -> str:
    lines = [
        f"PROVIDER={plan.provider_name}",
        f"CONFIGURED={plan.configured_count}",
        f"LIVE={plan.live_count}",
        f"ADD={len(plan.add)}",
        f"MISSING_GRACE={len(plan.keep_missing)}",
        f"REMOVE={len(plan.remove)}",
        f"UNCHANGED={len(plan.unchanged)}",
    ]

    if plan.add:
        lines.extend([
            "",
            "ADD_NOW:",
        ])

        for model in plan.add:
            lines.append(f"  + {model}")

    if plan.keep_missing:
        lines.extend([
            "",
            "MISSING_GRACE:",
        ])

        for model in plan.keep_missing:
            lines.append(f"  ? {model}")

    if plan.remove:
        lines.extend([
            "",
            "REMOVE_AFTER_GRACE:",
        ])

        for model in plan.remove:
            lines.append(f"  - {model}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Atomic catalog reconciliation application
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RemovedModelImpact:
    model: str
    mutable_references: tuple[ModelReference, ...]
    audit_references: tuple[ModelReference, ...]
    suggested_replacements: tuple[str, ...]


def _catalog_sync_backup_dir(
    hermes_home: Path,
) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = hermes_home / "backups"

    candidate = base / f"model-catalog-sync-{stamp}"
    suffix = 0

    while candidate.exists():
        suffix += 1
        candidate = base / (
            f"model-catalog-sync-{stamp}-{suffix}"
        )

    candidate.mkdir(
        parents=True,
        exist_ok=False,
    )
    candidate.chmod(0o700)

    return candidate


def _build_removed_model_impacts(
    removed_models: tuple[str, ...],
    hermes_home: Path,
) -> list[RemovedModelImpact]:
    impacts: list[RemovedModelImpact] = []

    for model_id in removed_models:
        refs = scan_model_references(
            model_id,
            hermes_home,
        )

        mutable = tuple(
            ref for ref in refs
            if ref.mutable
        )

        audit = tuple(
            ref for ref in refs
            if not ref.mutable
        )

        # Important:
        # suggestions are advisory only.
        candidates = suggest_capability_replacements(
            model_id,
            hermes_home,
            limit=8,
        )

        impacts.append(
            RemovedModelImpact(
                model=model_id,
                mutable_references=mutable,
                audit_references=audit,
                suggested_replacements=tuple(
                    candidate.model
                    for candidate in candidates
                ),
            )
        )

    return impacts


def apply_catalog_reconcile(
    provider_name: str = "AnyModel",
    hermes_home: Path | None = None,
    *,
    confirmed: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply one successful authoritative catalog reconciliation.

    Scope:
    - add newly discovered models immediately;
    - keep missing models during grace period;
    - remove models only after grace policy is satisfied;
    - never change model.default;
    - never change provider selected model;
    - never change routing or sessions;
    - never auto-replace referenced removed models.
    """

    if not confirmed:
        raise PermissionError(
            "Catalog reconciliation requires explicit confirmed=True"
        )

    import yaml

    home = hermes_home or (Path.home() / ".hermes")
    config_path = home / "config.yaml"
    state_path = _reconcile_state_path(home)

    cfg = yaml.safe_load(
        config_path.read_text(encoding="utf-8")
    ) or {}

    provider = _get_custom_provider_entry(
        cfg,
        provider_name,
    )

    if provider is None:
        raise ValueError(
            f"Custom provider not found: {provider_name}"
        )

    # Only Hermes-managed discovered catalogs are safe for automatic rewrite.
    if provider.get("models_discovered") is not True:
        raise RuntimeError(
            f"{provider_name} catalog is not Hermes-managed "
            "(models_discovered != true)"
        )

    default_before = (
        cfg.get("model", {}).get("default")
        if isinstance(cfg.get("model"), dict)
        else None
    )

    provider_model_before = provider.get("model")

    # Performs an authoritative live probe.
    # If the probe fails, this raises BEFORE any state/config mutation.
    plan, next_state = build_catalog_reconcile_plan(
        provider_name,
        home,
        now=now,
    )

    # Existing order is preserved.
    current_models = _catalog_ids_from_entry(
        provider
    )

    remove_set = set(plan.remove)

    final_models = [
        model_id
        for model_id in current_models
        if model_id not in remove_set
    ]

    existing = set(final_models)

    # New live models are appended in provider order.
    for model_id in plan.add:
        if model_id not in existing:
            final_models.append(model_id)
            existing.add(model_id)

    # No config mutation necessary if only reconciliation state changed.
    catalog_changed = (
        tuple(final_models)
        != tuple(current_models)
    )

    backup_dir = _catalog_sync_backup_dir(home)

    config_backup = backup_dir / "config.yaml"
    shutil.copy2(
        config_path,
        config_backup,
    )

    state_backup: Path | None = None
    state_existed = state_path.exists()

    if state_existed:
        state_backup = (
            backup_dir
            / "model_reconcile_state.json"
        )
        shutil.copy2(
            state_path,
            state_backup,
        )

    try:
        if catalog_changed:
            # Re-resolve provider entry from cfg in case references matter.
            provider = _get_custom_provider_entry(
                cfg,
                provider_name,
            )

            if provider is None:
                raise RuntimeError(
                    "Provider disappeared during reconciliation"
                )

            provider["models"] = {
                model_id: {}
                for model_id in final_models
            }

            provider["models_discovered"] = True

            # Invariants: catalog sync must not select another model.
            default_after = (
                cfg.get("model", {}).get("default")
                if isinstance(cfg.get("model"), dict)
                else None
            )

            if default_after != default_before:
                raise RuntimeError(
                    "Catalog reconciliation attempted to change model.default"
                )

            if provider.get("model") != provider_model_before:
                raise RuntimeError(
                    "Catalog reconciliation attempted to change "
                    "provider selected model"
                )

            _atomic_write_yaml(
                config_path,
                cfg,
            )

        # Persist missing/grace state only after config write succeeds.
        save_reconcile_state(
            next_state,
            home,
        )

        # Reload and verify invariants from disk.
        check = yaml.safe_load(
            config_path.read_text(encoding="utf-8")
        ) or {}

        check_provider = _get_custom_provider_entry(
            check,
            provider_name,
        )

        if check_provider is None:
            raise RuntimeError(
                "Provider missing after catalog write"
            )

        check_default = (
            check.get("model", {}).get("default")
            if isinstance(check.get("model"), dict)
            else None
        )

        if check_default != default_before:
            raise RuntimeError(
                "model.default changed during catalog reconciliation"
            )

        if check_provider.get("model") != provider_model_before:
            raise RuntimeError(
                "Provider selected model changed during reconciliation"
            )

        check_models = set(
            _catalog_ids_from_entry(
                check_provider
            )
        )

        for model_id in plan.add:
            if model_id not in check_models:
                raise RuntimeError(
                    f"New model was not persisted: {model_id}"
                )

        for model_id in plan.remove:
            if model_id in check_models:
                raise RuntimeError(
                    f"Expired missing model remains: {model_id}"
                )

    except Exception:
        # Config rollback.
        shutil.copy2(
            config_backup,
            config_path,
        )

        # Reconciliation-state rollback.
        if state_existed and state_backup is not None:
            shutil.copy2(
                state_backup,
                state_path,
            )
        elif not state_existed:
            with contextlib.suppress(FileNotFoundError):
                state_path.unlink()

        raise

    impacts = _build_removed_model_impacts(
        plan.remove,
        home,
    )

    return {
        "status": "PASS",
        "provider": provider_name,
        "configured_before": plan.configured_count,
        "live": plan.live_count,
        "added": list(plan.add),
        "missing_grace": list(plan.keep_missing),
        "removed": list(plan.remove),
        "catalog_changed": catalog_changed,
        "final_count": len(final_models),
        "default_model": default_before,
        "provider_model": provider_model_before,
        "backup_dir": str(backup_dir),
        "removed_impacts": [
            {
                "model": impact.model,
                "mutable_references": [
                    {
                        "source": ref.source,
                        "location": ref.location,
                    }
                    for ref in impact.mutable_references
                ],
                "audit_references": len(
                    impact.audit_references
                ),
                "suggested_replacements": list(
                    impact.suggested_replacements
                ),
            }
            for impact in impacts
        ],
    }
