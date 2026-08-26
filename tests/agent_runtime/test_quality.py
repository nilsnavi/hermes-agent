from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from agent.agent_runtime import AgentPermissions
from agent.agent_runtime.exceptions import AgentContractError
from agent.agent_runtime.quality import (
    AgentQualityModel,
    AgentQualitySnapshot,
    ValidationEvidence,
)
from agent.agent_runtime.registry import AgentDefinition, AgentRegistry


class MutableString(str):
    matches: bool

    def __new__(cls, value: str) -> "MutableString":
        instance = super().__new__(cls, value)
        instance.matches = True
        return instance

    def __eq__(self, other: object) -> bool:
        return self.matches and super().__eq__(other)

    __hash__ = str.__hash__


def make_definition(agent_id: str, version: int = 1) -> AgentDefinition:
    return AgentDefinition(
        agent_id=agent_id,
        version=version,
        name=agent_id,
        role="validator" if agent_id.startswith("validator") else "worker",
        implementation_id=agent_id,
        capabilities=("validate",),
        trust_score=0.5,
        permissions=AgentPermissions(read_files=True),
    )


def make_registry() -> AgentRegistry:
    registry = AgentRegistry(["subject", "validator-a", "validator-b"])
    registry.register(make_definition("subject"))
    registry.register(make_definition("validator-a"))
    registry.register(make_definition("validator-b"))
    return registry


def evidence(**overrides: object) -> ValidationEvidence:
    values: dict[str, object] = {
        "evidence_id": "evidence-1",
        "subject_key": ("subject", 1),
        "run_id": "run-1",
        "validator_key": ("validator-a", 1),
        "successful": True,
        "validation_score": 0.8,
        "latency_ms": 10.0,
    }
    values.update(overrides)
    return ValidationEvidence(**values)  # type: ignore[arg-type]


def test_empty_snapshot_is_frozen_and_all_zero() -> None:
    model = AgentQualityModel(make_registry())
    snapshot = model.get(("subject", 1))

    assert snapshot.subject_key == ("subject", 1)
    assert snapshot.evidence_count == 0
    assert snapshot.successful_runs == 0
    assert snapshot.success_rate == 0.0
    assert snapshot.mean_validation_score == 0.0
    assert snapshot.mean_latency_ms == 0.0
    assert snapshot.retry_rate == 0.0
    assert snapshot.quality_score == 0.0
    with pytest.raises(FrozenInstanceError):
        snapshot.evidence_count = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_id", ""),
        ("evidence_id", "x" * 65_537),
        ("subject_key", ["subject", 1]),
        ("subject_key", ("", 1)),
        ("subject_key", ("subject", True)),
        ("run_id", "   "),
        ("validator_key", ("validator-a", 0)),
        ("successful", 1),
        ("validation_score", True),
        ("validation_score", -0.01),
        ("validation_score", 1.01),
        ("validation_score", float("nan")),
        ("validation_score", float("inf")),
        ("latency_ms", True),
        ("latency_ms", -0.01),
        ("latency_ms", float("nan")),
        ("latency_ms", float("inf")),
        ("was_retry", 0),
    ],
)
def test_evidence_rejects_invalid_contract_values(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        evidence(**{field: value})


def test_record_requires_exact_registered_subject_and_validator() -> None:
    model = AgentQualityModel(make_registry())

    with pytest.raises(KeyError):
        model.record(evidence(subject_key=("missing", 1)))
    with pytest.raises(KeyError):
        model.record(evidence(validator_key=("validator-a", 2)))


def test_record_rejects_logical_self_validation_across_versions() -> None:
    registry = AgentRegistry(["subject"])
    registry.register(make_definition("subject"))
    registry.register(make_definition("subject", version=2))
    model = AgentQualityModel(registry)

    with pytest.raises(ValueError):
        model.record(evidence(validator_key=("subject", 2)))


def test_evidence_deduplication_is_idempotent_but_conflicts_are_denied() -> None:
    model = AgentQualityModel(make_registry())
    original = evidence()

    first_snapshot = model.record(original)
    assert isinstance(first_snapshot, AgentQualitySnapshot)
    assert first_snapshot.evidence_count == 1
    assert model.record(evidence()) == first_snapshot
    with pytest.raises(ValueError):
        model.record(evidence(validation_score=0.7))
    with pytest.raises(ValueError):
        model.record(evidence(evidence_id="evidence-2"))

    different_validator = evidence(
        evidence_id="evidence-3",
        validator_key=("validator-b", 1),
    )
    assert model.record(different_validator).evidence_count == 2


def test_aggregates_without_rounding_and_does_not_change_definition_authority() -> None:
    registry = make_registry()
    model = AgentQualityModel(registry)
    original_definition = registry.get("subject", 1)
    model.record(evidence())
    model.record(
        evidence(
            evidence_id="evidence-2",
            run_id="run-2",
            successful=False,
            validation_score=0.4,
            latency_ms=20.0,
            was_retry=True,
        )
    )
    model.record(
        evidence(
            evidence_id="evidence-3",
            run_id="run-3",
            validation_score=0.6,
            latency_ms=30.0,
        )
    )

    snapshot = model.get(("subject", 1))
    assert snapshot.evidence_count == 3
    assert snapshot.successful_runs == 2
    assert snapshot.success_rate == 2 / 3
    assert snapshot.mean_validation_score == (0.8 + 0.4 + 0.6) / 3
    assert snapshot.mean_latency_ms == 20.0
    assert snapshot.retry_rate == 1 / 3
    assert snapshot.quality_score == 0.5 * (2 / 3) + 0.5 * ((0.8 + 0.4 + 0.6) / 3)
    assert registry.get("subject", 1) == original_definition


def test_snapshots_are_sorted_detached_and_isolate_exact_versions() -> None:
    registry = make_registry()
    registry.register(make_definition("subject", version=2))
    model = AgentQualityModel(registry)
    model.record(evidence(evidence_id="v2", subject_key=("subject", 2)))
    first = model.snapshot()
    model.record(evidence())

    assert tuple(item.subject_key for item in first) == (("subject", 2),)
    assert tuple(item.subject_key for item in model.snapshot()) == (
        ("subject", 1),
        ("subject", 2),
    )
    assert first[0].evidence_count == 1
    assert model.get(("subject", 1)).evidence_count == 1
    assert model.get(("subject", 2)).evidence_count == 1


def test_public_exports_and_exact_quality_surface() -> None:
    from agent.agent_runtime import (
        AgentDefinition as ExportedDefinition,
        AgentQualityModel as ExportedQualityModel,
        AgentQualitySnapshot,
        AgentRegistry as ExportedRegistry,
        ValidationEvidence as ExportedEvidence,
    )

    assert ExportedDefinition is AgentDefinition
    assert ExportedRegistry is AgentRegistry
    assert ExportedEvidence is ValidationEvidence
    assert ExportedQualityModel is AgentQualityModel
    assert tuple(item.name for item in fields(ValidationEvidence)) == (
        "evidence_id",
        "subject_key",
        "run_id",
        "validator_key",
        "successful",
        "validation_score",
        "latency_ms",
        "was_retry",
    )
    assert tuple(item.name for item in fields(AgentQualitySnapshot)) == (
        "subject_key",
        "evidence_count",
        "successful_runs",
        "success_rate",
        "mean_validation_score",
        "mean_latency_ms",
        "retry_rate",
        "quality_score",
    )
    model = AgentQualityModel(make_registry())
    for forbidden in ("save", "load", "route", "persist"):
        assert not hasattr(model, forbidden)


def test_quality_copies_evidence_on_input_and_return_without_changing_dedupe() -> None:
    model = AgentQualityModel(make_registry())
    supplied = evidence()
    returned = model.record(supplied)

    object.__setattr__(supplied, "validation_score", 0.0)
    object.__setattr__(returned, "evidence_count", 999)
    replayed = model.record(evidence())
    assert replayed.evidence_count == 1
    assert replayed.mean_validation_score == 0.8
    snapshot = model.get(("subject", 1))
    assert snapshot.evidence_count == 1
    assert snapshot.mean_validation_score == 0.8

    object.__setattr__(snapshot, "evidence_count", 999)
    assert model.get(("subject", 1)).evidence_count == 1


def test_quality_normalizes_string_subclasses_before_deduplication() -> None:
    model = AgentQualityModel(make_registry())
    aliased_evidence_id = MutableString("evidence-1")
    aliased_run_id = MutableString("run-1")
    supplied = evidence(
        evidence_id=aliased_evidence_id,
        run_id=aliased_run_id,
    )

    assert model.record(supplied).evidence_count == 1
    aliased_evidence_id.matches = False
    aliased_run_id.matches = False

    assert model.record(evidence()).evidence_count == 1


def test_quality_uses_slots_and_hides_old_publicish_store_names() -> None:
    model = AgentQualityModel(make_registry())

    assert not hasattr(model, "__dict__")
    assert not hasattr(model, "_evidence_by_id")
    assert not hasattr(model, "_evidence_keys")


@pytest.mark.parametrize("field", ["validation_score", "latency_ms"])
def test_huge_integer_numeric_inputs_raise_contract_error(field: str) -> None:
    with pytest.raises(AgentContractError):
        evidence(**{field: 10**10_000})


def test_record_normalizes_corrupted_huge_numeric_input_without_mutation() -> None:
    model = AgentQualityModel(make_registry())
    corrupted = evidence()
    object.__setattr__(corrupted, "latency_ms", 10**10_000)

    with pytest.raises(AgentContractError):
        model.record(corrupted)
    assert model.snapshot() == ()


def test_latency_aggregation_overflow_fails_atomically() -> None:
    model = AgentQualityModel(make_registry())
    model.record(evidence(latency_ms=1e308))
    before = model.snapshot()

    with pytest.raises(AgentContractError):
        model.record(evidence(evidence_id="evidence-2", run_id="run-2", latency_ms=1e308))

    assert model.snapshot() == before


def test_failed_quality_conflicts_are_atomic() -> None:
    model = AgentQualityModel(make_registry())
    model.record(evidence())
    before = model.snapshot()

    with pytest.raises(AgentContractError):
        model.record(evidence(validation_score=0.2))
    assert model.snapshot() == before

    with pytest.raises(AgentContractError):
        model.record(evidence(evidence_id="other-id"))
    assert model.snapshot() == before
