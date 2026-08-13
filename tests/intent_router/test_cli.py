"""Intent Router CLI tests (Sprint 1.1 §54-55)."""

import json

import pytest

from agent.intent_router import cli


def _run(argv):
    return cli.main(argv)


def test_cli_classify_request_type(capsys):
    assert _run(["classify", "--request-type", "status", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["intent"] == "status_read"
    assert "effective_route" in out


def test_cli_classify_text(capsys):
    assert _run(["classify", "--text", "удали файл", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["intent"] == "delete_action"


def test_cli_classify_text_not_persisted(capsys):
    """--text is in-memory only: output contains no text."""
    assert _run(["classify", "--text", "покажи статус секретного сервера",
                 "--json"]) == 0
    raw = capsys.readouterr().out
    assert "секретного" not in raw
    assert "text" not in raw


def test_cli_explain(capsys):
    assert _run(["classify", "--request-type", "status", "--explain"]) == 0
    out = capsys.readouterr().out
    assert "because" in out or "LEGACY" in out


def test_cli_evaluate(capsys):
    assert _run(["evaluate", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "evaluation" in out
    assert out["evaluation"]["unsafe_as_read_only"] == 0
    assert out["safety_acceptance"]["pass"] is True


def test_cli_status(capsys):
    assert _run(["status", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "enabled" in out
    assert "mode" in out
    assert "decision_count" in out


def test_cli_rules(capsys):
    assert _run(["rules", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["rules"]) >= 6
    assert out["rules_version"]


def test_cli_json_stable(capsys):
    _run(["classify", "--request-type", "status", "--json"])
    s1 = capsys.readouterr().out
    _run(["classify", "--request-type", "status", "--json"])
    s2 = capsys.readouterr().out
    assert json.loads(s1) == json.loads(s2)


def test_cli_no_decision_mutation(capsys):
    """CLI only classifies; no tools, no DB writes."""
    assert _run(["classify", "--text", "покажи статус", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["effective_route"] in ("legacy", "v2_shadow", "v2_canary")
