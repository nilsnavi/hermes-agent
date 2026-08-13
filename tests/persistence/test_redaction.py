"""Redaction tests (Sprint 1.0.3 §26 / §27 / §28 / §29).

Sensitive payloads must never reach the DB in plaintext: step arguments,
tool results and event payloads are scrubbed at the store boundary; hashes
are computed on the SCRUBBED canonical JSON.
"""

import pytest

from agent.execution.models import ExecutionPlan, ExecutionStep, StepStatus
from agent.persistence import SQLiteExecutionStore
from agent.persistence.redaction import (
    REDACTED,
    canonical_json,
    is_sensitive_key,
    scrub,
    scrub_and_hash,
    sha256_hex,
)
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.states import RunStatus
from datetime import datetime, timezone

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


def test_scrub_flat_dict():
    out = scrub({"api_key": "sk-secret", "repo": "navitech"})
    assert out == {"api_key": REDACTED, "repo": "navitech"}


def test_scrub_case_insensitive_keys():
    assert scrub({"API_KEY": "x"})["API_KEY"] == REDACTED
    assert scrub({"Authorization": "Bearer x"})["Authorization"] == REDACTED
    assert scrub({"Cookie": "a=b"})["Cookie"] == REDACTED


def test_scrub_nested_dict_and_list():
    out = scrub({"outer": {"token": "t", "ok": 1}, "items": [{"password": "p"}, 42]})
    assert out == {"outer": {"token": REDACTED, "ok": 1},
                   "items": [{"password": REDACTED}, 42]}


def test_scrub_does_not_match_substrings():
    # Exact key match only — token_count / session_id must survive.
    assert scrub({"token_count": 5, "session_id": "s"}) == {
        "token_count": 5, "session_id": "s",
    }


def test_is_sensitive_key():
    assert is_sensitive_key("api_key") is True
    assert is_sensitive_key("TOKEN") is True
    assert is_sensitive_key("token_count") is False


def test_canonical_json_stable():
    a = canonical_json({"b": 1, "a": [2, 1]})
    b = canonical_json({"a": [2, 1], "b": 1})
    assert a == b


def test_sha256_deterministic_and_unicode():
    h1 = sha256_hex({"привет": "мир"})
    h2 = sha256_hex({"привет": "мир"})
    assert h1 == h2
    assert len(h1) == 64


def test_scrub_and_hash():
    safe, digest = scrub_and_hash({"token": "t", "n": 1})
    assert safe == {"token": REDACTED, "n": 1}
    assert digest == sha256_hex(safe)


def test_arguments_scrubbed_on_write(tmp_path):
    store = SQLiteExecutionStore(str(tmp_path / "s.db"))
    store.save_run(AgentRun(id="r1", task_type="t", status=RunStatus.CREATED,
                            model_profile="BALANCED", created_at=T0))
    store.save_plan(ExecutionPlan(id="p1", run_id="r1", goal="g", created_at=T0))
    store.save_step("p1", ExecutionStep(
        id="s1", name="call", description="", tool="api",
        arguments={"api_key": "sk-plain", "payload": {"nested": {"password": "pw"}}},
        status=StepStatus.READY,
    ))
    loaded = store.get_step("p1", "s1")
    assert loaded.arguments["api_key"] == REDACTED
    assert loaded.arguments["payload"]["nested"]["password"] == REDACTED
    store.close()


def test_result_scrubbed_on_write(tmp_path):
    store = SQLiteExecutionStore(str(tmp_path / "s.db"))
    store.save_run(AgentRun(id="r1", task_type="t", status=RunStatus.CREATED,
                            model_profile="BALANCED", created_at=T0))
    run = store.get_run("r1")
    run.result = {"output": "ok", "authorization": "Bearer sekrit"}
    store.update_run(run)
    loaded = store.get_run("r1")
    assert loaded.result is not None
    assert loaded.result["authorization"] == REDACTED
    store.close()


def test_event_payload_scrubbed_on_append(tmp_path):
    store = SQLiteExecutionStore(str(tmp_path / "s.db"))
    store.append_event(RuntimeEvent(
        event_type="TOOL_STARTED", run_id="r1", timestamp=T0,
        payload={"step": "s1", "credentials": {"token": "t"}},
    ))
    events = store.list_events(run_id="r1")
    assert events[0].payload["credentials"]["token"] == REDACTED
    store.close()


# ── Sprint 1.0.6.2 §60-61: redaction hardening ────────────────────────────


def test_scrub_extended_secret_keys():
    """§60 — api_token/auth_token/session_token must now be redacted."""
    out = scrub({"api_token": "t1", "auth_token": "t2", "session_token": "t3",
                 "access_token": "t4", "client_secret": "c", "private_key": "k"})
    assert all(v == REDACTED for v in out.values())


def test_scrub_normalized_mixed_case_camel():
    """§61 — camelCase / mixed-case variants caught by the matcher."""
    assert scrub({"API_TOKEN": "x"})["API_TOKEN"] == REDACTED
    assert scrub({"apiToken": "x"})["apiToken"] == REDACTED
    assert scrub({"accessToken": "x"})["accessToken"] == REDACTED
    assert scrub({"Auth_Token": "x"})["Auth_Token"] == REDACTED
    assert scrub({"SessionToken": "x"})["SessionToken"] == REDACTED


def test_scrub_does_not_overredact_generic_fields():
    """§60 — token_count / session_id / key_count survive (no over-redaction)."""
    out = scrub({"token_count": 3, "session_id": "s", "key_count": 1,
                 "monkey": 1, "keyboard": "q"})
    assert out == {"token_count": 3, "session_id": "s", "key_count": 1,
                   "monkey": 1, "keyboard": "q"}


def test_scrub_nested_secret_variants():
    """§61 — nested dicts and lists with secret variants all redacted."""
    out = scrub({
        "payload": {
            "headers": {"Authorization": "Bearer x", "api_token": "y"},
            "list": [{"client_secret": "z"}, {"sessionToken": "s"}],
        },
        "meta": {"token_count": 7},
    })
    assert out["payload"]["headers"]["Authorization"] == REDACTED
    assert out["payload"]["headers"]["api_token"] == REDACTED
    assert out["payload"]["list"][0]["client_secret"] == REDACTED
    assert out["payload"]["list"][1]["sessionToken"] == REDACTED
    assert out["meta"]["token_count"] == 7  # generic field survives


def test_scrub_flat_no_plaintext():
    """§61 — flat dict: no secret value survives in any form."""
    out = scrub({"api_token": "sk-abc-123", "password": "pw", "authorization": "x"})
    blob = str(out)
    assert "sk-abc-123" not in blob and "pw" not in blob and "x" not in blob
    assert all(v == REDACTED for v in out.values())


def test_is_sensitive_key_extended():
    assert is_sensitive_key("api_token") is True
    assert is_sensitive_key("API_TOKEN") is True
    assert is_sensitive_key("apiToken") is True
    assert is_sensitive_key("auth_token") is True
    assert is_sensitive_key("session_token") is True
    assert is_sensitive_key("access_token") is True
    assert is_sensitive_key("client_secret") is True
    # generic fields stay non-sensitive
    assert is_sensitive_key("token_count") is False
    assert is_sensitive_key("session_id") is False
    assert is_sensitive_key("monkey") is False


def test_hash_of_extended_secret_is_scrubbed():
    """§60 — input hashes cover scrubbed canon: api_token value never
    influences the digest (secret redacted BEFORE hashing)."""
    h1 = sha256_hex(scrub({"api_token": "AAA"}))
    h2 = sha256_hex(scrub({"api_token": "BBB"}))
    assert h1 == h2  # both scrub to the same canonical [REDACTED]
    assert "AAA" not in h1 and "BBB" not in h1
