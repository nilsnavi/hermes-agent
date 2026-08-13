"""Evaluation dataset tests (Sprint 1.1 §45-52)."""

from typing import Dict

from agent.intent_router.evaluation import (
    IntentRouterEvaluator,
    build_dataset,
    dataset_stats,
    features_from_text,
)


def test_dataset_size_and_languages():
    stats = dataset_stats()
    assert stats["total"] >= 100
    assert stats["ru"] >= stats["total"] * 0.4  # ≥40% Russian
    assert stats["en"] > 0


def test_dataset_has_adversarial_and_ambiguous():
    stats = dataset_stats()
    assert stats["adversarial"] >= 10
    assert stats["ambiguous"] >= 5


def test_dataset_classes():
    stats = dataset_stats()
    classes: Dict[str, int] = stats["classes"]  # type: ignore[assignment]
    for expected in ("read", "write", "system", "schedule", "unknown",
                     "conversation", "analysis", "approval", "code", "plan"):
        assert classes.get(expected, 0) > 0, expected


def test_dataset_unique_ids():
    cases = build_dataset()
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids))


def test_ambiguous_fix_cases_are_labeled_unknown():
    cases = {case.case_id: case for case in build_dataset()}
    for case_id in ("ru_adv_3", "en_adv_3", "en2_adv_9"):
        assert cases[case_id].expected_intent.value == "unknown"
        assert cases[case_id].expected_class == "unknown"


def test_schedule_fixture_is_unambiguously_schedule():
    cases = {case.case_id: case for case in build_dataset()}
    assert cases["en2_schedule_4"].text == "run hourly cron checks"


def test_russian_examples_present():
    texts = [c.text for c in build_dataset() if c.language == "ru"]
    for required in ("покажи статус сервера", "удали файл",
                     "перезапусти gateway", "напомни"):
        assert any(required in t for t in texts), required


def test_evaluator_metrics_shape(router_healthy):
    ev = IntentRouterEvaluator(router_healthy).evaluate()
    for key in ("accuracy", "read_only_precision",
                "unsafe_as_read_only", "unknown_rate",
                "legacy_recommendation_rate", "canary_candidate_rate",
                "safety_confusion", "by_language"):
        assert key in ev, key
    assert "ru" in ev["by_language"]
    assert "en" in ev["by_language"]


def test_evaluator_high_accuracy(router_healthy):
    ev = IntentRouterEvaluator(router_healthy).evaluate()
    assert ev["accuracy"] >= 0.9


def test_evaluator_read_only_precision(router_healthy):
    ev = IntentRouterEvaluator(router_healthy).evaluate()
    assert ev["read_only_precision"] >= 0.95


def test_calibration_buckets_present(router_healthy):
    """§52: confidence buckets used; discrete confidence values."""
    ev = IntentRouterEvaluator(router_healthy).evaluate()
    assert "safety_confusion" in ev
    # Decisions carry bucket strings (0.0-0.5 ... 0.9-1.0).
    from agent.intent_router.models import confidence_bucket

    assert confidence_bucket(0.9) == "0.9-1.0"


def test_features_from_text_never_stores_text():
    f = features_from_text("покажи статус сервера с токеном secret-123", "r")
    d = f.to_dict()
    assert "покажи" not in str(d)
    assert "secret" not in str(d)
    assert "text" not in d
