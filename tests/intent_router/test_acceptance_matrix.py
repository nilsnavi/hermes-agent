"""Acceptance corpus + A/B matrix tests (methodology from HCO).

Перенесено из hermes-context-optimizer: детерминированный acceptance
корпус (каждый кейс — один инвариант), A/B serious matrix
(детерминизм, дисперсия), no-raw-text (секретная изоляция).
"""

import pytest

from agent.intent_router.acceptance_matrix import (
    acceptance_corpus,
    check_acceptance,
    check_no_raw_text,
    run_ab_matrix,
)
from agent.intent_router.classifier import RuleBasedIntentClassifier
from agent.intent_router.evaluation import build_dataset


def _router_factory():
    """Свежий роутер через классификатор (детерминированный)."""
    from agent.intent_router.router import IntentRouter

    return IntentRouter(classifier=RuleBasedIntentClassifier())


def test_acceptance_corpus_size():
    assert len(acceptance_corpus()) >= 8
    safety = [c for c in acceptance_corpus() if c.safety_critical]
    assert len(safety) >= 4


def test_acceptance_corpus_has_both_languages():
    langs = {c.language for c in acceptance_corpus()}
    assert "ru" in langs and "en" in langs


def test_acceptance_all_invariants_pass():
    assert check_acceptance(_router_factory()) is True


def test_no_raw_text_secret_isolation():
    assert check_no_raw_text() is True


def test_ab_matrix_deterministic_accuracy(router_healthy):
    """A/B matrix: 3 свежих роутера дают идентичную accuracy."""
    res = run_ab_matrix(router_healthy, runs=3)
    assert res["runs"] == 3
    assert res["accuracy"]["deterministic"] is True
    assert res["accuracy"]["std"] == 0.0


def test_ab_matrix_safety_zero_every_run(router_healthy):
    res = run_ab_matrix(router_healthy, runs=3)
    assert res["safety"]["all_zero"] is True
    assert res["safety"]["acceptance_pass_all"] is True


def test_ab_matrix_acceptance_pass_all_runs(router_healthy):
    res = run_ab_matrix(router_healthy, runs=2)
    assert res["acceptance_corpus"]["pass_all_runs"] is True
    assert res["acceptance_corpus"]["total"] == len(acceptance_corpus())


def test_ab_matrix_dataset_size_matches_build():
    res = run_ab_matrix(_router_factory, runs=2)
    assert res["dataset_size"] == len(build_dataset())


def test_acceptance_safety_cases_never_canary(router_healthy):
    """§75: safety-critical acceptance-кейсы никогда не кандидаты canary."""
    for case in acceptance_corpus():
        if not case.safety_critical:
            continue
        decision = router_healthy.observe(
            __import__(
                "agent.intent_router.evaluation", fromlist=["features_from_text"]
            ).features_from_text(case.text, case.case_id)
        )
        assert decision.candidate_route != "v2_canary", case.case_id
