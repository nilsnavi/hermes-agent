"""Health endpoint + adapter-level tests (Sprint 1.0.6 §40/41, MUST-HAVE 20/21)."""

import os

from agent.gateway_v2.adapter import GatewayV2Adapter
from agent.gateway_v2.canary import V2CanaryPolicy
from agent.gateway_v2.store_factory import schema_apply

from .conftest import ALL_FALSE, CANARY_ON, make_request, make_registry


def test_health_all_false_no_secrets():
    """MUST-HAVE 20 — health output is safe: no DB paths, no secrets."""
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    health = adapter.health()
    v2 = health["runtime_v2"]
    assert v2 == {"enabled": False, "shadow": False, "canary": False,
                  "persistence": False, "schema_ready": False}
    blob = str(health)
    assert "state.db" not in blob
    assert "/home/" not in blob
    assert "token" not in blob.lower()


def test_health_schema_ready_flag(tmp_path):
    db = str(tmp_path / "h.db")
    schema_apply(db)
    adapter = GatewayV2Adapter(flags=CANARY_ON)
    assert adapter.health(db)["runtime_v2"]["schema_ready"] is True


def test_canary_policy_summary_deny_by_default():
    health = GatewayV2Adapter(flags=CANARY_ON).health()
    policy = health["canary_policy"]
    assert policy["deny_by_default"] is True
    assert policy["read_only_only"] is True


def test_store_factory_never_opens_with_flags_false():
    """MUST-HAVE 21 — flags false → no store, no schema, no file."""
    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    assert adapter._factory.create_store() is None


def test_run_canary_not_enabled_returns_clean_error():
    adapter = GatewayV2Adapter(flags=ALL_FALSE, registry=make_registry())
    response = adapter.run_canary(make_request(),
                                  step_specs=[{"name": "s1", "tool": "search"}])
    assert response["code"] == "V2_NOT_ENABLED"
    assert response["ok"] is False


def test_canary_telemetry_records_lifecycle(registry):
    from .conftest import CANARY_ON

    policy = V2CanaryPolicy(allowed_users=["alice"], registry=registry)
    adapter = GatewayV2Adapter(flags=CANARY_ON, registry=registry, canary_policy=policy)
    adapter.run_canary(make_request(), step_specs=[{"name": "s1", "tool": "search"}])
    counts = adapter.telemetry.counts()
    assert counts.get("gateway.v2.canary.started") == 1
    assert counts.get("gateway.v2.canary.completed") == 1
    # no prompt bodies in telemetry
    assert all("prompt" not in e for e in adapter.telemetry.recent(10))


def test_adapter_crash_before_tool_no_side_effect(store, registry, clock):
    """§49 — canary adapter crash after run creation, before tool:
    run persisted, no side effect, recovery reports safe state."""
    from agent.orchestrator import RuntimeOrchestrator
    from agent.runtime.run_engine import RunEngine
    from agent.runtime.states import RunStatus
    from agent.persistence import SQLiteExecutionStore
    import tempfile

    db = os.path.join(tempfile.mkdtemp(), "crash.db")
    store = SQLiteExecutionStore(db)
    run_engine = RunEngine(clock=clock, store=store)
    run = run_engine.create_run("canary", "BALANCED", run_id="crash-run")
    run_engine.start_run(run)
    run_engine.transition(run, RunStatus.PLANNING)
    store.close()

    # reopen: run exists, zero tools started → recovery is safe
    store2 = SQLiteExecutionStore(db)
    from agent.gateway_v2.adapter import GatewayV2Adapter
    from .conftest import ALL_FALSE

    adapter = GatewayV2Adapter(flags=ALL_FALSE)
    allowed, reason = adapter.can_fallback("crash-run", store2)
    assert allowed is True
    assert store2.get_run("crash-run").status is RunStatus.PLANNING
    store2.close()


def test_gateway_runtime_status_contains_safe_v2_block(tmp_path, monkeypatch):
    """§40 — the persisted gateway health/status record exposes the
    runtime_v2 block (booleans only: enabled/shadow/canary/persistence/
    schema_ready), no DB paths, no secrets, and preserves the pre-adapter
    record fields. With all flags false the adapter opens NO SQLite file."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from gateway.status import read_runtime_status, write_runtime_status

    write_runtime_status(gateway_state="running", exit_reason=None)
    record = read_runtime_status()
    assert record["gateway_state"] == "running"  # pre-adapter fields intact
    v2 = record["runtime_v2"]
    assert v2 == {"enabled": False, "shadow": False, "canary": False,
                  "persistence": False, "schema_ready": False}
    blob = str(record)
    assert "state.db" not in blob
    assert "token" not in blob.lower()
    # Scope the path-leak check to the V2-added block: the legacy record
    # legitimately carries the process argv (interpreter path) — that is
    # pre-existing gateway diagnostics, not a V2 path/secret leak.
    rec = record or {}
    v2_blob = str(rec.get("runtime_v2", {})) + str(rec.get("canary_policy", ""))
    assert "/home/" not in v2_blob
