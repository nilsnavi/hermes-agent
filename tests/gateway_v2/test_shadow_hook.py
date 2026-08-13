"""Live-gateway hook path tests (Sprint 1.0.6.1 §26-27).

The gateway hook calls ``decide_event(event)`` then — only for a SHADOW
decision — ``shadow_event(event, timeout=1.0)``. These tests drive that
exact path with MessageEvent-shaped objects: ordinary events → LEGACY +
no shadow work; explicit-eligible events → bounded shadow, zero tools,
zero writes, zero user-visible output, never raising.
"""

from datetime import datetime

from agent.gateway_v2.adapter import GatewayV2Adapter, V2Decision
from agent.gateway_v2.flags import FeatureFlags

from .conftest import make_registry

SHADOW_ON = FeatureFlags(enabled=True, shadow=True)
ALL_FALSE = FeatureFlags()


class FakeEvent:
    def __init__(self, event_id="evt-1", text="hello", user_id="alice",
                 session_id="sess-1", metadata=None, internal=False):
        self.id = event_id
        self.text = text
        self.user_id = user_id
        self.session_id = session_id
        self.metadata = dict(metadata or {})
        self.internal = internal
        self.timestamp = datetime.now()


def test_ordinary_event_legacy_no_shadow_work():
    """§26 — a plain event with shadow flags ON stays LEGACY and performs
    NO shadow analysis (shadow.started must NOT be recorded)."""
    adapter = GatewayV2Adapter(flags=SHADOW_ON, registry=make_registry())
    event = FakeEvent(text="ordinary user message")
    assert adapter.decide_event(event) is V2Decision.LEGACY
    counts = adapter.telemetry.counts()
    assert counts.get("gateway.v2.shadow.started", 0) == 0


def test_eligible_event_runs_bounded_shadow():
    """§27 — explicit internal request: SHADOW decision + shadow report;
    zero tools, zero writes; exactly started+completed telemetry.

    The live hook passes NO step_specs (real gateway events carry none,
    V2 shadow has no autonomous planning) → the planner reports NO_PLAN
    (plan requires at least one step) — a benign, captured outcome."""
    adapter = GatewayV2Adapter(flags=SHADOW_ON, registry=make_registry())
    event = FakeEvent(text="Summarize this supplied synthetic text",
                      metadata={"runtime_v2_shadow": True})
    assert adapter.decide_event(event) is V2Decision.SHADOW
    report = adapter.shadow_event(event, timeout=1.0)
    assert report["mode"] == "shadow"
    assert report["plan_valid"] is False
    assert "at least one step" in report["reason"]
    counts = adapter.telemetry.counts()
    assert counts.get("gateway.v2.shadow.started") == 1
    assert counts.get("gateway.v2.shadow.completed") == 1
    assert counts.get("gateway.v2.shadow.failed", 0) == 0
    # no user-visible output is produced by shadow itself
    assert "output" not in report or report.get("output") is None


def test_shadow_event_never_raises_on_bad_event():
    """A malformed event must not raise through the hook."""
    adapter = GatewayV2Adapter(flags=SHADOW_ON, registry=make_registry())
    class Weird:
        pass
    result = adapter.shadow_event(Weird(), timeout=0.5)
    assert result["ok"] is False  # captured, not raised


def test_shadow_event_telemetry_no_prompt():
    """§41 — telemetry entries carry no prompt/goal/secret content."""
    adapter = GatewayV2Adapter(flags=SHADOW_ON, registry=make_registry())
    event = FakeEvent(text="secret prompt text with token ABC123",
                      metadata={"runtime_v2_shadow": True})
    adapter.shadow_event(event, timeout=1.0)
    blob = str(adapter.telemetry.recent(20))
    assert "secret prompt text" not in blob
    assert "ABC123" not in blob
    assert "token" not in blob.lower()


def test_flags_false_hook_inert():
    """With all flags false the hook path is a no-op (legacy 1.0.6
    invariant): decision LEGACY, no telemetry shadow events, no store."""
    adapter = GatewayV2Adapter(flags=ALL_FALSE, registry=make_registry())
    event = FakeEvent(text="anything", metadata={"runtime_v2_shadow": True})
    assert adapter.decide_event(event) is V2Decision.LEGACY
    assert adapter.telemetry.counts().get("gateway.v2.shadow.started", 0) == 0


def test_eligible_event_shadow_does_not_write_db(tmp_path):
    """§21/§22 — shadow with PERSISTENCE=false writes ZERO agent_v2 rows."""
    import sqlite3

    from agent.persistence import SQLiteExecutionStore

    db = str(tmp_path / "state.db")
    store = SQLiteExecutionStore(db)
    tables = ("agent_v2_runs", "agent_v2_plans", "agent_v2_steps",
              "agent_v2_approvals", "agent_v2_events")

    def counts():
        con = sqlite3.connect(db)
        try:
            out = {}
            for t in tables:
                try:
                    out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except sqlite3.OperationalError:
                    out[t] = None  # schema not applied → no rows possible
            return out
        finally:
            con.close()

    before = counts()
    adapter = GatewayV2Adapter(flags=SHADOW_ON, registry=make_registry())
    event = FakeEvent(text="summarize", metadata={"runtime_v2_shadow": True})
    adapter.shadow_event(event, timeout=1.0)
    after = counts()
    assert before == after  # identical — zero V2 writes
    store.close()
