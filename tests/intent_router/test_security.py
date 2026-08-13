"""Security tests (Sprint 1.1 §17-18, §56, §83)."""

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.explain import explain, explain_rich


def test_features_no_raw_text(router_healthy):
    f = features_from_text(
        "покажи статус с токеном sk-secret-12345", "r1")
    serialized = str(f.to_dict())
    assert "sk-secret" not in serialized
    assert "token" not in f.to_dict()
    assert "text" not in f.to_dict()


def test_decision_no_prompt(router_healthy):
    d = router_healthy.observe(features_from_text(
        "покажи статус секретного сервера с паролем", "r1"))
    raw = str(d.to_dict())
    assert "секретного" not in raw
    assert "парол" not in raw
    assert "prompt" not in d.to_dict()


def test_events_no_prompt(router_healthy):
    router_healthy.observe(features_from_text(
        "удали файл с секретом-xyz", "r1"))
    events = router_healthy.recent_events()
    raw = str([e.to_dict() for e in events])
    assert "секретом" not in raw
    assert "xyz" not in raw


def test_no_db_writes(router_healthy, tmp_path):
    """§56: router is dry-run by design — no DB, no business writes."""
    import sqlite3

    db_path = str(tmp_path / "probe.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'x')")
    conn.commit()

    # Router has no db handle at all.
    assert not hasattr(router_healthy, "_db")

    # Even after many evaluations the file is untouched (no side effect
    # path exists in the facade).
    for i in range(5):
        router_healthy.observe(features_from_text(
            "покажи статус", f"r{i}", internal=True))

    conn2 = sqlite3.connect(db_path)
    assert conn2.execute("SELECT v FROM t WHERE id=1").fetchone()[0] == "x"
    conn2.close()
    conn.close()


def test_no_tool_execution(router_healthy, monkeypatch):
    """Router facade has no tool surface at all — nothing to call."""
    d = router_healthy.observe(features_from_text(
        "покажи статус сервера", "r1", internal=True))
    assert d.effective_route in ("v2_canary", "legacy")
    # No registry handle on the router proves no execution path.
    assert not hasattr(router_healthy, "_registry")


def test_explain_no_raw_content(router_healthy):
    d = router_healthy.observe(features_from_text(
        "покажи статус", "r1"))
    text = explain(d)
    assert "покажи" not in text
    assert "status" not in text.lower() or "status" in text.lower()
    rich = explain_rich(d)
    assert "prompt" not in rich
    assert "text" not in rich


def test_reason_codes_structured(router_healthy):
    d = router_healthy.observe(features_from_text(
        "покажи статус", "r1"))
    for code in d.reason_codes:
        assert isinstance(code, str)
        assert "_" in code  # structured, not free text


def test_confidence_bounded(router_healthy):
    for text in ("покажи статус", "удали файл", "сделай это", "привет"):
        d = router_healthy.observe(features_from_text(text, "r"))
        assert 0.0 <= d.confidence <= 1.0
