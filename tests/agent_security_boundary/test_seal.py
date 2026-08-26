"""seal.py: the sandbox adapter is runtime-owned and sealed.

Direct invocation of a sealed sandbox from outside the gate must be DENIED.
Only the gate's private token unlocks it; admission (this phase) never invokes
`run`, so real adapter calls stay 0.
"""

import pytest

from agent.agent_security_boundary.exceptions import SealViolation
from agent.agent_security_boundary.seal import SealedSandbox


class _StubAdapter:
    def __init__(self):
        self.calls = 0

    def run(self, payload):
        self.calls += 1
        return "ran"


def test_sealed_sandbox_present_only_when_adapter_wired():
    assert SealedSandbox(None).is_present is False
    assert SealedSandbox(_StubAdapter()).is_present is True


def test_sealed_sandbox_is_always_flagged_sealed():
    assert SealedSandbox(_StubAdapter()).is_sealed is True


def test_direct_adapter_call_without_token_is_denied():
    sandbox = SealedSandbox(_StubAdapter())
    with pytest.raises(SealViolation):
        sandbox.run({"capability": "write_files"})
    assert sandbox.call_count == 0


def test_forged_token_does_not_unlock():
    sandbox = SealedSandbox(_StubAdapter())
    with pytest.raises(SealViolation):
        sandbox.run(
            {"capability": "write_files"},
            gate_token="APPROVED",  # caller verdict string is not a token
        )
    with pytest.raises(SealViolation):
        sandbox.run({"capability": "write_files"}, gate_token=object())
    assert sandbox.call_count == 0


def test_no_public_accessor_returning_the_seal_token():
    # The B1 closure: the seal token must be unobtainable by any public API.
    sandbox = SealedSandbox(_StubAdapter())
    with pytest.raises(AttributeError):
        _ = sandbox._gate_token()  # type: ignore[attr-defined]  # removed accessor
    with pytest.raises(AttributeError):
        _ = SealedSandbox._gate_token()  # type: ignore[attr-defined]
    # No instance attribute exposes the token.
    assert not hasattr(sandbox, "gate_token")
    assert not hasattr(sandbox, "_GATE_TOKEN")


def test_run_is_uncallable_without_an_obtainable_token():
    adapter = _StubAdapter()
    sandbox = SealedSandbox(adapter)
    # No caller can supply the correct token, so run always fails closed and the
    # underlying adapter is NEVER invoked (call_count stays 0).
    for forged in (None, "APPROVED", object(), 123, "gate_token"):
        with pytest.raises(SealViolation):
            sandbox.run({"capability": "analyze_code"}, gate_token=forged)
    assert sandbox.call_count == 0
    assert adapter.calls == 0


def test_sealed_sandbox_rejects_no_adapter_execution():
    # No adapter -> even a (hypothetical) valid token must fail closed.
    sandbox = SealedSandbox(None)
    with pytest.raises(SealViolation):
        sandbox.run({"capability": "analyze_code"})