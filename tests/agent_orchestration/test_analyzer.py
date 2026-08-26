"""Task Analyzer tests."""

import pytest

from agent.agent_orchestration.analyzer import InvalidAnalysisInput, TaskAnalyzer


def test_read_goal_is_read_only():
    analysis = TaskAnalyzer.analyze("исследуй рынок", "t1")
    assert analysis.read_only
    assert "task_analysis" in analysis.suggested_capabilities


def test_write_goal_is_not_read_only():
    analysis = TaskAnalyzer.analyze("создай отчёт", "t2")
    assert not analysis.read_only
    assert "planning" in analysis.suggested_capabilities


def test_memory_hint_adds_retrieval():
    analysis = TaskAnalyzer.analyze("вспомни нашу стратегию и создай план", "t3")
    assert "memory_retrieval" in analysis.suggested_capabilities


def test_verify_hint_marks_verification():
    analysis = TaskAnalyzer.analyze("проверь результаты", "t4")
    assert analysis.requires_verification
    assert "validation" in analysis.suggested_capabilities


def test_english_keywords():
    analysis = TaskAnalyzer.analyze("write code for the module", "t5")
    assert not analysis.read_only

    read = TaskAnalyzer.analyze("read the config", "t6")
    assert read.read_only


def test_empty_goal_rejected():
    with pytest.raises(InvalidAnalysisInput):
        TaskAnalyzer.analyze("", "t1")
    with pytest.raises(InvalidAnalysisInput):
        TaskAnalyzer.analyze("goal", "")


def test_analyzer_has_no_execution_surface():
    assert not hasattr(TaskAnalyzer, "execute")
    assert not hasattr(TaskAnalyzer, "run")
    assert not hasattr(TaskAnalyzer, "authorize")
    assert not hasattr(TaskAnalyzer, "grant")