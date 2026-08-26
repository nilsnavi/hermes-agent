"""Immutable validation evidence and deterministic agent quality aggregates."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .exceptions import AgentContractError
from .registry import AgentRegistry

AgentKey = tuple[str, int]
_MAX_TEXT_LENGTH = 65_536


def _require_identifier(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AgentContractError(f"{name} must be a non-empty string")
    if len(value) > _MAX_TEXT_LENGTH:
        raise AgentContractError(f"{name} exceeds the {_MAX_TEXT_LENGTH}-character limit")


def _require_agent_key(name: str, value: object) -> None:
    if not isinstance(value, tuple) or len(value) != 2:
        raise AgentContractError(f"{name} must be an (agent_id, version) tuple")
    agent_id, version = value
    _require_identifier(f"{name} agent_id", agent_id)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise AgentContractError(f"{name} version must be a positive integer")


def _require_finite_number(name: str, value: object, *, maximum: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AgentContractError(f"{name} must be a finite number in range")
    try:
        normalized_value = float(value)
    except (OverflowError, ValueError):
        normalized_value = math.nan
    if (
        not math.isfinite(normalized_value)
        or normalized_value < 0
        or (maximum is not None and normalized_value > maximum)
    ):
        raise AgentContractError(f"{name} must be a finite number in range")


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    evidence_id: str
    subject_key: AgentKey
    run_id: str
    validator_key: AgentKey
    successful: bool
    validation_score: float
    latency_ms: float
    was_retry: bool = False

    def __post_init__(self) -> None:
        _require_identifier("evidence_id", self.evidence_id)
        _require_agent_key("subject_key", self.subject_key)
        _require_identifier("run_id", self.run_id)
        _require_agent_key("validator_key", self.validator_key)
        if type(self.successful) is not bool:
            raise AgentContractError("successful must be a bool")
        _require_finite_number("validation_score", self.validation_score, maximum=1)
        _require_finite_number("latency_ms", self.latency_ms)
        if type(self.was_retry) is not bool:
            raise AgentContractError("was_retry must be a bool")
        object.__setattr__(self, "evidence_id", str(self.evidence_id))
        object.__setattr__(
            self,
            "subject_key",
            (str(self.subject_key[0]), int(self.subject_key[1])),
        )
        object.__setattr__(self, "run_id", str(self.run_id))
        object.__setattr__(
            self,
            "validator_key",
            (str(self.validator_key[0]), int(self.validator_key[1])),
        )
        object.__setattr__(self, "validation_score", float(self.validation_score))
        object.__setattr__(self, "latency_ms", float(self.latency_ms))


@dataclass(frozen=True, slots=True)
class AgentQualitySnapshot:
    subject_key: AgentKey
    evidence_count: int
    successful_runs: int
    success_rate: float
    mean_validation_score: float
    mean_latency_ms: float
    retry_rate: float
    quality_score: float


class AgentQualityModel:
    __slots__ = ("__registry", "__evidence_by_id", "__evidence_keys")

    def __init__(self, registry: AgentRegistry) -> None:
        if type(registry) is not AgentRegistry:
            raise AgentContractError("registry must be an exact AgentRegistry")
        self.__registry = registry
        self.__evidence_by_id: dict[str, ValidationEvidence] = {}
        self.__evidence_keys: dict[tuple[AgentKey, str, AgentKey], str] = {}

    @staticmethod
    def __copy_evidence(evidence: ValidationEvidence) -> ValidationEvidence:
        return ValidationEvidence(
            evidence_id=evidence.evidence_id,
            subject_key=(evidence.subject_key[0], evidence.subject_key[1]),
            run_id=evidence.run_id,
            validator_key=(evidence.validator_key[0], evidence.validator_key[1]),
            successful=evidence.successful,
            validation_score=evidence.validation_score,
            latency_ms=evidence.latency_ms,
            was_retry=evidence.was_retry,
        )

    @staticmethod
    def __require_safe_aggregation(evidence: tuple[ValidationEvidence, ...]) -> None:
        try:
            validation_total = sum(item.validation_score for item in evidence)
            latency_total = sum(item.latency_ms for item in evidence)
            count = len(evidence)
            validation_mean = validation_total / count
            latency_mean = latency_total / count
        except (OverflowError, ValueError) as exc:
            raise AgentContractError("evidence cannot be aggregated safely") from exc
        if not math.isfinite(validation_mean) or not math.isfinite(latency_mean):
            raise AgentContractError("evidence cannot be aggregated safely")

    def record(self, evidence: ValidationEvidence) -> AgentQualitySnapshot:
        if type(evidence) is not ValidationEvidence:
            raise AgentContractError("evidence must be an exact ValidationEvidence value")
        copied_evidence = self.__copy_evidence(evidence)
        self.__registry.get(*copied_evidence.subject_key)
        self.__registry.get(*copied_evidence.validator_key)
        if copied_evidence.subject_key[0] == copied_evidence.validator_key[0]:
            raise AgentContractError("an agent cannot validate itself")
        existing = self.__evidence_by_id.get(copied_evidence.evidence_id)
        if existing is not None:
            if existing == copied_evidence:
                return self.get(existing.subject_key)
            raise AgentContractError("evidence_id is already used by different evidence")
        logical_key = (
            copied_evidence.subject_key,
            copied_evidence.run_id,
            copied_evidence.validator_key,
        )
        if logical_key in self.__evidence_keys:
            raise AgentContractError("validator already supplied evidence for this run")
        subject_evidence = tuple(
            item
            for item in self.__evidence_by_id.values()
            if item.subject_key == copied_evidence.subject_key
        ) + (copied_evidence,)
        self.__require_safe_aggregation(subject_evidence)
        self.__evidence_by_id[copied_evidence.evidence_id] = copied_evidence
        self.__evidence_keys[logical_key] = copied_evidence.evidence_id
        return self.get(copied_evidence.subject_key)

    def get(self, subject_key: AgentKey) -> AgentQualitySnapshot:
        _require_agent_key("subject_key", subject_key)
        self.__registry.get(*subject_key)
        evidence = tuple(
            item
            for item in self.__evidence_by_id.values()
            if item.subject_key == subject_key
        )
        evidence_count = len(evidence)
        if evidence_count == 0:
            return AgentQualitySnapshot(
                subject_key=subject_key,
                evidence_count=0,
                successful_runs=0,
                success_rate=0.0,
                mean_validation_score=0.0,
                mean_latency_ms=0.0,
                retry_rate=0.0,
                quality_score=0.0,
            )
        successful_runs = sum(item.successful for item in evidence)
        success_rate = successful_runs / evidence_count
        mean_validation_score = (
            sum(item.validation_score for item in evidence) / evidence_count
        )
        mean_latency_ms = sum(item.latency_ms for item in evidence) / evidence_count
        retry_rate = sum(item.was_retry for item in evidence) / evidence_count
        return AgentQualitySnapshot(
            subject_key=subject_key,
            evidence_count=evidence_count,
            successful_runs=successful_runs,
            success_rate=success_rate,
            mean_validation_score=mean_validation_score,
            mean_latency_ms=mean_latency_ms,
            retry_rate=retry_rate,
            quality_score=0.5 * success_rate + 0.5 * mean_validation_score,
        )

    def snapshot(self) -> tuple[AgentQualitySnapshot, ...]:
        subject_keys = sorted({item.subject_key for item in self.__evidence_by_id.values()})
        return tuple(self.get(subject_key) for subject_key in subject_keys)
