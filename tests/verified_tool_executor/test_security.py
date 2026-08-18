"""Sprint 1.3.2 §35/§16/§17 — security: no raw secrets/prompt in
telemetry; input/output hashes are computed on SCRUBBED payloads."""

from agent.verified_tool_executor.executor import VerifiedToolExecutor
from agent.verified_tool_executor.hashing import (
    compute_input_hash,
    compute_output_hash,
)
from agent.verified_tool_executor.models import ExecutionStatus
from agent.verified_tool_executor.registry import VerifiedToolRegistry
from agent.verified_tool_executor.receipts import MemoryReceiptStore
from tests.verified_tool_executor.conftest import (
    RecordingAdapter,
    make_request,
)

#: A tool whose schema legitimately accepts arbitrary string args —
#: used to prove raw secrets never leak into telemetry even when the
#: arguments themselves are schema-valid.
_LOOSE_SCHEMA = {"fields": {"secret": {"type": "str", "required": False},
                            "query": {"type": "str", "required": False}}}


def _executor(adapter):
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", adapter,
             argument_schema=_LOOSE_SCHEMA)
    return VerifiedToolExecutor(reg, receipts=MemoryReceiptStore())


def test_input_hash_scrubs_secrets():
    """§16 — input_hash is computed on the SANITIZED input: two
    arguments dicts differing only in a secret value hash EQUAL
    (the secret never influences the telemetry identifier)."""
    a = compute_input_hash({"token": "sk-secret-aaa"})
    b = compute_input_hash({"token": "sk-secret-bbb"})
    assert a == b
    c = compute_input_hash({"token": "sk-secret-aaa", "scope": "x"})
    assert a != c  # structure still matters


def test_output_hash_scrubs_secrets():
    """§17 — output_hash never legitimizes storing plaintext."""
    a = compute_output_hash({"data": "ok", "api_key": "k-111"})
    b = compute_output_hash({"data": "ok", "api_key": "k-222"})
    assert a == b


def test_events_carry_no_raw_arguments():
    """§18/§35 — TOOL_STARTED carries execution_id/tool/input_hash,
    never raw arguments."""
    adapter = RecordingAdapter(output={"ok": True})
    ex = _executor(adapter)
    ex.execute(make_request(arguments={"secret": "sk-raw"}))
    started = [e for e in ex.events if e.event_type == "TOOL_STARTED"]
    assert len(started) == 1
    blob = str(started[0].to_dict())
    assert "sk-raw" not in blob
    assert "secret" not in blob


def test_receipts_carry_no_raw_payload():
    adapter = RecordingAdapter(output={"ok": True})
    ex = _executor(adapter)
    ex.execute(make_request(arguments={"secret": "hunter2"},
                            metadata={"goal": "x"}))
    blob = str(ex.receipts.all()[0].to_dict())
    assert "hunter2" not in blob
    assert "secret" not in blob


def test_events_never_contain_traceback():
    class ExplodingAdapter:
        def execute(self, context, arguments):
            raise ValueError("shh")

    ex = _executor(ExplodingAdapter())
    ex.execute(make_request())
    blob = "".join(str(e.to_dict()) for e in ex.events)
    assert "Traceback" not in blob
    assert "shh" not in blob


def test_goal_is_bounded_in_context():
    """The goal handed to adapters is truncated to 500 chars."""
    adapter = RecordingAdapter(output={"ok": True})
    ex = _executor(adapter)
    long_goal = "x" * 5000
    ex.execute(make_request(metadata={"goal": long_goal}))
    ctx, _ = adapter.calls[0]
    assert len(ctx.goal) <= 500


def test_operator_context_never_reaches_events():
    adapter = RecordingAdapter(output={"ok": True})
    ex = _executor(adapter)
    ex.execute(make_request(
        operator_context={"authorization": "Bearer sk-111"}))
    blob = "".join(str(e.to_dict()) for e in ex.events)
    assert "sk-111" not in blob
