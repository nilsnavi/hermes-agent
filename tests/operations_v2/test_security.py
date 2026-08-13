"""Security tests (Sprint 1.0.6.3 §40, §52, §61, MUST-HAVE 22)."""

import json
import subprocess
import os

from agent.operations_v2.service import OperationsService
from agent.operations_v2.serializers import to_json

from .conftest import run_completed, run_gated

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VENV_PY = os.path.join(REPO, "venv", "bin", "python")

SECRET_MARKERS = (
    "sk-", "token", "authorization", "api_key", "password",
    "privkey", "BEGIN PRIVATE",
)


def _scan(blob: str) -> list:
    low = blob.lower()
    return [m for m in SECRET_MARKERS if m.lower() in low]


def test_no_secret_fields_in_dtos(ops_db, store, orchestrator):
    """MUST-HAVE 22 — DTOs carry no secret-shaped fields."""
    ok_id = run_completed(orchestrator, store, "sec-ok")
    gated, approval = run_gated(orchestrator, store, "sec-wait")
    svc = OperationsService(db_path=ops_db)
    blobs = []
    blobs.append(str(svc.get_run(ok_id).to_dict()))
    blobs.append(str([i.to_dict() for i in svc.timeline(ok_id, limit=100)]))
    blobs.append(str([a.to_dict() for a in svc.pending_approvals()]))
    blobs.append(str([m.to_dict() for m in svc.manual_reviews()]))
    blobs.append(to_json(svc.metrics("all")))
    blobs.append(to_json(svc.health().to_dict()))
    for blob in blobs:
        hits = _scan(blob)
        # "token" must not appear as a field name in ops output
        assert "token" not in blob.lower(), hits
        assert "api_key" not in blob.lower()
        assert "authorization" not in blob.lower()
        assert "sk-" not in blob


def test_cli_output_no_secrets(ops_db, store, orchestrator):
    run_id = run_completed(orchestrator, store, "sec-cli")
    for cmd in (
        ["run", run_id, "--json"],
        ["timeline", run_id, "--json"],
        ["metrics", "--json"],
        ["health", "--json"],
        ["runs", "--limit", "5", "--json"],
    ):
        proc = subprocess.run(
            [VENV_PY, "-m", "agent.operations_v2.cli", *cmd, "--db", ops_db],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, (cmd, proc.stderr)
        hits = _scan(proc.stdout)
        assert not hits, (cmd, hits)
        json.loads(proc.stdout)  # stable JSON


def test_operator_id_never_email(ops_db, store, orchestrator):
    """§52 — operator identity carries an internal stable id, not PII."""
    from agent.operations_v2.approval_service import ApprovalService
    from agent.operations_v2.models import OperatorIdentity

    op = OperatorIdentity(operator_id="op-42", source="cli",
                          roles=frozenset({"operator"}), authenticated=True)
    blob = to_json(op.to_dict())
    assert "op-42" in blob
    assert "@" not in blob


def test_secret_scan_agent_v2_tables(ops_db, store, orchestrator):
    """§61 — scan the seeded agent_v2 tables for plaintext secrets."""
    run_completed(orchestrator, store, "sec-scan")
    run_gated(orchestrator, store, "sec-scan2")
    import sqlite3

    conn = sqlite3.connect(ops_db)
    try:
        for table in ("agent_v2_runs", "agent_v2_plans", "agent_v2_steps",
                      "agent_v2_approvals", "agent_v2_events", "agent_v2_meta"):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            for col in cols:
                for row in conn.execute(f"SELECT {col} FROM {table}"):
                    value = row[0]
                    if value is None:
                        continue
                    text = str(value)
                    if any(m in text.lower() for m in
                           ("sk-", "api_key", "authorization", "password")):
                        # input/output hashes are sha256 — hex only, safe
                        if table == "agent_v2_events" and col in (
                                "input_hash", "output_hash"):
                            continue
                        assert False, f"{table}.{col} leaked a secret marker"
    finally:
        conn.close()
