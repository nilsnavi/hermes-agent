from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

import hermes_cli.model_reconcile as mr


OLD = "am/old-model"
NEW = "am/new-model"
KEEP = "am/keep-model"


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def _basic_config(
    *,
    default_model: str = OLD,
    provider_model: str = KEEP,
) -> dict:
    return {
        "model": {
            "default": default_model,
        },
        "custom_providers": [
            {
                "name": "AnyModel",
                "base_url": "https://example.invalid/v1",
                "model": provider_model,
                "models_discovered": True,
                "models": {
                    OLD: {},
                    NEW: {},
                    KEEP: {},
                },
            }
        ],
    }


def _caps(
    *,
    tools: bool = True,
    vision: bool = True,
    reasoning: bool = True,
    context: int = 128000,
) -> mr.ResolvedCapabilities:
    return mr.ResolvedCapabilities(
        known=True,
        provider="test-provider",
        model="test-model",
        supports_tools=tools,
        supports_vision=vision,
        supports_reasoning=reasoning,
        context_window=context,
        model_family="test-family",
        source="test",
    )


def test_reference_scanner_excludes_catalog_and_preserves_session_audit(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".hermes"
    home.mkdir()

    cfg = _basic_config()
    _write_yaml(home / "config.yaml", cfg)

    db = sqlite3.connect(home / "state.db")

    try:
        db.execute(
            """
            CREATE TABLE gateway_routing (
                scope TEXT,
                session_key TEXT,
                entry_json TEXT
            )
            """
        )
        db.execute(
            """
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY,
                session_key TEXT,
                model TEXT,
                ended_at TEXT
            )
            """
        )

        db.execute(
            """
            INSERT INTO gateway_routing(scope, session_key, entry_json)
            VALUES (?, ?, ?)
            """,
            (
                "telegram",
                "session-1",
                json.dumps(
                    {
                        "model_override": {
                            "model": OLD,
                        }
                    }
                ),
            ),
        )

        db.execute(
            """
            INSERT INTO sessions(id, session_key, model, ended_at)
            VALUES (?, ?, ?, NULL)
            """,
            (1, "session-1", OLD),
        )

        db.commit()

    finally:
        db.close()

    refs = mr.scan_model_references(OLD, home)

    locations = {ref.location for ref in refs}

    assert "model.default" in locations

    assert not any(
        "custom_providers" in ref.location
        and ".models" in ref.location
        for ref in refs
    )

    routing = [
        ref
        for ref in refs
        if ref.kind == "runtime_override"
    ]
    audit = [
        ref
        for ref in refs
        if ref.kind == "active_session_audit"
    ]

    assert len(routing) == 1
    assert routing[0].mutable is True

    assert len(audit) == 1
    assert audit[0].mutable is False


@pytest.mark.parametrize(
    "state",
    [
        mr.QUARANTINED,
        mr.RETIRED,
    ],
)
def test_quarantined_and_retired_models_are_blocked(
    tmp_path: Path,
    state: str,
) -> None:
    home = tmp_path / ".hermes"
    home.mkdir()

    mr.set_model_health(
        NEW,
        state,
        reason="test",
        hermes_home=home,
    )

    assert mr.model_health_state(NEW, home) == state
    assert mr.model_allowed_as_replacement(NEW, home) is False


def test_capability_compatibility_rejects_degradation() -> None:
    requirements = mr.ReplacementRequirements(
        known=True,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        min_context_window=128000,
        family="test-family",
    )

    missing_vision = _caps(
        vision=False,
        context=128000,
    )

    short_context = _caps(
        context=64000,
    )

    compatible = _caps(
        context=256000,
    )

    assert (
        mr.capability_compatible(
            missing_vision,
            requirements,
        )
        is False
    )

    assert (
        mr.capability_compatible(
            short_context,
            requirements,
        )
        is False
    )

    assert (
        mr.capability_compatible(
            compatible,
            requirements,
        )
        is True
    )


def test_apply_model_replacement_changes_mutable_yaml_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".hermes"
    home.mkdir()

    config_path = home / "config.yaml"
    _write_yaml(
        config_path,
        _basic_config(),
    )

    plan = mr.ReplacementPlan(
        old_model=OLD,
        new_model=NEW,
        mutable_references=(
            mr.ModelReference(
                source="config.yaml",
                location="model.default",
                model=OLD,
                mutable=True,
                kind="config",
            ),
        ),
        audit_references=(),
        replacement_caps=_caps(),
    )

    monkeypatch.setattr(
        mr,
        "build_transactional_replacement_plan",
        lambda *args, **kwargs: plan,
    )

    result = mr.apply_model_replacement(
        OLD,
        NEW,
        hermes_home=home,
        confirmed=True,
    )

    assert result["status"] == "PASS"
    assert result["yaml_changes"] == 1

    updated = yaml.safe_load(
        config_path.read_text(encoding="utf-8")
    )

    assert updated["model"]["default"] == NEW

    provider = updated["custom_providers"][0]

    # Provider catalog is availability data and must not be rewritten
    # by the model-reference replacement transaction.
    assert OLD in provider["models"]
    assert NEW in provider["models"]


def test_apply_model_replacement_rolls_back_yaml_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".hermes"
    home.mkdir()

    config_path = home / "config.yaml"

    original = _basic_config()

    _write_yaml(
        config_path,
        original,
    )

    original_text = config_path.read_text(
        encoding="utf-8"
    )

    plan = mr.ReplacementPlan(
        old_model=OLD,
        new_model=NEW,
        mutable_references=(
            mr.ModelReference(
                source="config.yaml",
                location="model.default",
                model=OLD,
                mutable=True,
                kind="config",
            ),
        ),
        audit_references=(),
        replacement_caps=_caps(),
    )

    monkeypatch.setattr(
        mr,
        "build_transactional_replacement_plan",
        lambda *args, **kwargs: plan,
    )

    def fail_after_write(
        path: Path,
        data: dict,
    ) -> None:
        path.write_text(
            yaml.safe_dump(
                data,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        raise RuntimeError(
            "synthetic write verification failure"
        )

    monkeypatch.setattr(
        mr,
        "_atomic_write_yaml",
        fail_after_write,
    )

    with pytest.raises(
        RuntimeError,
        match="synthetic write verification failure",
    ):
        mr.apply_model_replacement(
            OLD,
            NEW,
            hermes_home=home,
            confirmed=True,
        )

    assert (
        config_path.read_text(encoding="utf-8")
        == original_text
    )


def test_catalog_missing_requires_three_checks_and_24h(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".hermes"
    home.mkdir()

    diff = mr.CatalogDiff(
        provider_name="AnyModel",
        configured=(OLD, KEEP),
        live=(KEEP,),
        added=(),
        missing=(OLD,),
        unchanged=(KEEP,),
    )

    monkeypatch.setattr(
        mr,
        "diff_custom_provider_catalog",
        lambda *args, **kwargs: diff,
    )

    t0 = datetime(
        2026,
        9,
        20,
        12,
        0,
        tzinfo=timezone.utc,
    )

    plan1, state1 = mr.build_catalog_reconcile_plan(
        "AnyModel",
        home,
        now=t0,
    )

    assert plan1.keep_missing == (OLD,)
    assert plan1.remove == ()

    mr.save_reconcile_state(
        state1,
        home,
    )

    plan2, state2 = mr.build_catalog_reconcile_plan(
        "AnyModel",
        home,
        now=t0 + timedelta(hours=12),
    )

    assert plan2.keep_missing == (OLD,)
    assert plan2.remove == ()

    mr.save_reconcile_state(
        state2,
        home,
    )

    plan3, state3 = mr.build_catalog_reconcile_plan(
        "AnyModel",
        home,
        now=t0 + timedelta(hours=24),
    )

    assert plan3.keep_missing == ()
    assert plan3.remove == (OLD,)

    missing_state = (
        state3["providers"]["AnyModel"]["missing"]
    )

    # Removal policy has been satisfied; stale tracking state
    # must not remain forever.
    assert OLD not in missing_state


def test_catalog_reconcile_never_auto_replaces_referenced_removed_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".hermes"
    home.mkdir()

    config_path = home / "config.yaml"

    _write_yaml(
        config_path,
        _basic_config(
            default_model=OLD,
            provider_model=KEEP,
        ),
    )

    plan = mr.CatalogReconcilePlan(
        provider_name="AnyModel",
        live_count=2,
        configured_count=3,
        add=(),
        keep_missing=(),
        remove=(OLD,),
        unchanged=(NEW, KEEP),
    )

    next_state = {
        "providers": {
            "AnyModel": {
                "missing": {},
                "last_successful_sync_at": (
                    "2026-09-22T12:00:00+00:00"
                ),
                "last_live_count": 2,
            }
        }
    }

    monkeypatch.setattr(
        mr,
        "build_catalog_reconcile_plan",
        lambda *args, **kwargs: (
            plan,
            next_state,
        ),
    )

    monkeypatch.setattr(
        mr,
        "suggest_capability_replacements",
        lambda *args, **kwargs: [],
    )

    result = mr.apply_catalog_reconcile(
        "AnyModel",
        home,
        confirmed=True,
    )

    assert result["status"] == "PASS"
    assert result["removed"] == [OLD]

    updated = yaml.safe_load(
        config_path.read_text(encoding="utf-8")
    )

    provider = updated["custom_providers"][0]

    # Catalog membership is removed...
    assert OLD not in provider["models"]

    # ...but active routing/reference selection is never
    # automatically rewritten by catalog synchronization.
    assert updated["model"]["default"] == OLD
    assert provider["model"] == KEEP

    impacts = result["removed_impacts"]

    assert len(impacts) == 1
    assert impacts[0]["model"] == OLD

    locations = {
        ref["location"]
        for ref in impacts[0]["mutable_references"]
    }

    assert "model.default" in locations


def test_validate_replacement_target_accepts_compatible_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".hermes"
    home.mkdir()

    monkeypatch.setattr(
        mr,
        "get_anymodel_catalog",
        lambda *args, **kwargs: [OLD, NEW],
    )

    monkeypatch.setattr(
        mr,
        "replacement_requirements",
        lambda model_id: mr.ReplacementRequirements(
            known=True,
            supports_tools=True,
            supports_vision=True,
            supports_reasoning=False,
            min_context_window=128000,
            family="test-family",
        ),
    )

    compatible = mr.ResolvedCapabilities(
        known=True,
        provider="test-provider",
        model="new-model",
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        context_window=256000,
        model_family="test-family",
        source="test",
    )

    monkeypatch.setattr(
        mr,
        "resolve_model_capabilities",
        lambda *args, **kwargs: compatible,
    )

    result = mr.validate_replacement_target(
        OLD,
        NEW,
        home,
    )

    assert result == compatible


def test_validate_replacement_target_rejects_capability_degradation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".hermes"
    home.mkdir()

    monkeypatch.setattr(
        mr,
        "get_anymodel_catalog",
        lambda *args, **kwargs: [OLD, NEW],
    )

    monkeypatch.setattr(
        mr,
        "replacement_requirements",
        lambda model_id: mr.ReplacementRequirements(
            known=True,
            supports_tools=True,
            supports_vision=True,
            supports_reasoning=True,
            min_context_window=128000,
            family="test-family",
        ),
    )

    degraded = mr.ResolvedCapabilities(
        known=True,
        provider="test-provider",
        model="new-model",
        supports_tools=True,
        supports_vision=False,
        supports_reasoning=True,
        context_window=256000,
        model_family="test-family",
        source="test",
    )

    monkeypatch.setattr(
        mr,
        "resolve_model_capabilities",
        lambda *args, **kwargs: degraded,
    )

    with pytest.raises(
        ValueError,
        match="does not preserve required capabilities",
    ):
        mr.validate_replacement_target(
            OLD,
            NEW,
            home,
        )
