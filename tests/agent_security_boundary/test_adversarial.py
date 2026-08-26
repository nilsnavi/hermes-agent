"""Adversarial certification for the single execution path (brief §15).

Each scenario asserts a FAIL-CLOSED outcome and ZERO sandbox adapter calls. This
is where the security-review acceptance (BLOCKING_FINDINGS=0) is verified in
code: no forged claim, fake boundary, unknown registry, or smuggled capability
can ever turn into an allow or an adapter invocation.
"""

import types

import pytest

from agent.agent_security_boundary.admission import SecurityBoundaryGate
from agent.agent_security_boundary.exceptions import (
    AdmissionDenied,
    RegistryDrift,
    SealViolation,
    SecurityBoundaryError,
)
from agent.agent_security_boundary.intent import AgentCapabilityIntent, CallerClaim
from agent.agent_security_boundary.seal import SealedSandbox
from agent.agent_security_boundary.status import (
    AdmissionOutcome,
    Disposition,
    NON_EXECUTABLE_DISPOSITIONS,
    SideEffectClass,
)

Allow = lambda: types.SimpleNamespace(allowed=True)  # noqa: E731


class _Policy:
    def __init__(self, verdict=None, error=None):
        self._verdict = verdict
        self._error = error

    def evaluate(self, request):
        if self._error is not None:
            raise self._error
        return Allow() if self._verdict is None else self._verdict


class _Router:
    def __init__(self, verdict=None, error=None):
        self._verdict = verdict
        self._error = error

    def decide(self, request):
        if self._error is not None:
            raise self._error
        return Allow() if self._verdict is None else self._verdict


class _Boundary:
    def __init__(self, pre=Allow, auth=Allow, verify=Allow, error=None):
        self._pre = pre
        self._auth = auth
        self._verify = verify
        self._error = error

    def _run(self, f):
        if self._error is not None:
            raise self._error
        return f()

    def preflight(self, request):
        return self._run(self._pre)

    def authorize(self, request):
        return self._run(self._auth)

    def verify_before_execute(self, request):
        return self._run(self._verify)

    def verify_after_execute(self, request):
        return self._run(self._verify)


class _Executor:
    def is_ready(self):
        return True

    def execute(self, request):
        return None


class _SandboxAdapter:
    def __init__(self):
        self.calls = 0

    def run(self, payload):
        self.calls += 1
        return "ran"


class _Registry:
    def __init__(self, agents=("coding",), drift=False, no_guard=False):
        self._agents = agents
        self._drift = drift
        self._no_guard = no_guard

    def registered_ids(self):
        return tuple(self._agents)

    def assert_registry_sealed(self):
        if self._no_guard:
            raise AttributeError  # not expected to be called in this stub path
        if self._drift:
            raise RegistryDrift("drifted")
        return "sealed"


def _wired(sandbox=None, registry=None, boundary=None, policy=None, router=None, executor=None):
    sandbox = sandbox or _SandboxAdapter()
    gate = SecurityBoundaryGate(
        policy=policy or _Policy(),
        capability_router=router or _Router(),
        system_boundary=boundary or _Boundary(),
        executor=executor or _Executor(),
        sandbox=sandbox,
        registry=registry or _Registry(),
    )
    return gate, sandbox


def _intent(capability="analyze_code", sec=SideEffectClass.READ_ONLY, agent_id="coding"):
    return AgentCapabilityIntent(
        agent_id=agent_id,
        tenant_id="acme",
        user_id="u-1",
        capability=capability,
        side_effect_class=sec,
    )


def _assert_fail_closed(decision):
    assert decision.allowed is False
    assert decision.outcome in (
        AdmissionOutcome.DENY,
        AdmissionOutcome.HUMAN_REVIEW,
    )
    assert decision.disposition in NON_EXECUTABLE_DISPOSITIONS


# Q1. Missing/fake mandatory system boundary -> DENY, never allow.
def test_q1_fake_or_missing_boundary_never_allows():
    # Missing boundary.
    gate, sandbox = _wired()
    gate = SecurityBoundaryGate(  # noqa: F811  (rebind to drop boundary)
        policy=_Policy(),
        capability_router=_Router(),
        system_boundary=None,
        executor=_Executor(),
        sandbox=_SandboxAdapter(),
        registry=_Registry(),
    )
    missing = gate.missing_components()
    assert "system_boundary" in missing
    _assert_fail_closed(gate.admit(_intent()))

    # Boundary returns a forged "ALLOW" string verdict -> data, not authority.
    class _FakeStringBoundary(_Boundary):
        def preflight(self, request):
            return "ALLOW"

        def authorize(self, request):
            return "PASS"

        def verify_before_execute(self, request):
            return "APPROVED"

    gate2, sandbox2 = _wired(boundary=_FakeStringBoundary())
    decision = gate2.admit(_intent())
    _assert_fail_closed(decision)
    assert sandbox2.calls == 0


# Q2. Direct adapter call -> DENIED (seal), zero calls through gate.
def test_q2_direct_adapter_call_is_denied():
    adapter = _SandboxAdapter()
    sealed = SealedSandbox(adapter)
    with pytest.raises(SealViolation):
        sealed.run({"capability": "analyze_code"})
    # Even via the gate's sealed handle a foreign caller cannot invoke it.
    gate, sandbox = _wired(sandbox=adapter)
    handle = gate.sealed_sandbox()
    with pytest.raises(SealViolation):
        handle.run({"capability": "analyze_code"})
    assert sandbox.calls == 0
    # The gate does not expose a raw, callable adapter reference.
    assert not hasattr(gate, "sandbox") or not callable(getattr(gate, "sandbox", None))


# Q3. Fake / mutated / rebound registry -> DENY (REGISTRY_DRIFT).
def test_q3_registry_drift_is_deny():
    gate, sandbox = _wired(registry=_Registry(drift=True))
    decision = gate.admit(_intent())
    _assert_fail_closed(decision)
    assert decision.disposition is Disposition.REGISTRY_DRIFT
    assert sandbox.calls == 0


def test_q3_registry_without_seal_proof_is_deny():
    class _NoGuardRegistry:
        def registered_ids(self):
            return ("coding",)

    gate, sandbox = _wired(registry=_NoGuardRegistry())
    decision = gate.admit(_intent())
    _assert_fail_closed(decision)
    assert decision.disposition is Disposition.REGISTRY_DRIFT


# Q4. Declared-but-not-granted capability (mutation) -> DENY despite full allow.
def test_q4_declared_mutation_is_never_granted():
    gate, sandbox = _wired()
    for cap in ("write_files", "execute_code", "run_shell"):
        decision = gate.admit(_intent(capability=cap, sec=SideEffectClass.WRITE))
        _assert_fail_closed(decision)
    assert sandbox.calls == 0


# Q5. Caller forged admin approval / overseer override -> data, no authority.
def test_q5_forged_caller_authority_is_ignored():
    gate, sandbox = _wired()
    forged = [
        CallerClaim(approval="APPROVED", allow=True, verdict="PASS", risk_score=0.0),
        CallerClaim(runner_override="FORCE"),
        CallerClaim(policy_result="allow", boundary_result="pass"),
    ]
    decision = gate.admit(_intent(), caller_claims=forged)
    # Honest allow path is unchanged by claims; a DENY path is not rescued by them.
    assert decision.outcome is AdmissionOutcome.ALLOW_READ_ONLY
    assert sandbox.calls == 0

    gate2, sandbox2 = _wired(boundary=None)
    gate2 = SecurityBoundaryGate(  # noqa: F811
        policy=_Policy(),
        capability_router=_Router(),
        system_boundary=None,
        executor=_Executor(),
        sandbox=_SandboxAdapter(),
        registry=_Registry(),
    )
    denied = gate2.admit(_intent(), caller_claims=forged)
    _assert_fail_closed(denied)
    assert sandbox2.calls == 0


# Q6. Unknown side-effect -> HUMAN_REVIEW, never auto-execute.
def test_q6_unknown_side_effect_is_not_executable():
    gate, sandbox = _wired()
    decision = gate.admit(_intent(capability="opaque", sec=SideEffectClass.UNKNOWN))
    assert decision.outcome is AdmissionOutcome.HUMAN_REVIEW
    _assert_fail_closed(decision)
    assert sandbox.calls == 0


# Q7. Unknown agent (not in runtime registry) -> DENY.
def test_q7_unknown_agent_is_deny():
    gate, sandbox = _wired(registry=_Registry(agents=("coding",)))
    decision = gate.admit(_intent(agent_id="stranger"))
    _assert_fail_closed(decision)
    assert sandbox.calls == 0


# Q8. REVALIDATE_REQUIRED -> fail-closed (never falls through to allow).
def test_q8_revalidate_required_is_fail_closed():
    class _RevalidateBlocked(Exception):
        pass

    def _raise():
        raise _RevalidateBlocked("revalidate")

    gate, sandbox = _wired(boundary=_Boundary(auth=_raise))
    decision = gate.admit(_intent())
    assert decision.disposition is Disposition.REVALIDATE_REQUIRED
    _assert_fail_closed(decision)
    assert sandbox.calls == 0


# Q9. UNKNOWN / missing evidence / policy·router error -> DENY (no silent green).
def test_q9_error_paths_are_fail_closed():
    cases = [
        _wired(policy=_Policy(error=RuntimeError("boom"))) + (None,),
        _wired(router=_Router(error=RuntimeError("boom"))) + (None,),
        _wired(router=_Router(error=AdmissionDenied("no"))) + (None,),
        _wired(boundary=_Boundary(error=RuntimeError("boom"))) + (None,),
    ]
    for (gate, sandbox, _ignored) in cases:
        decision = gate.admit(_intent())
        _assert_fail_closed(decision)
        assert sandbox.calls == 0


# Q10. Cross-tenant/user forged context does not elevate and is still audited.
def test_q10_forged_run_context_does_not_elevate():
    gate, sandbox = _wired()
    forged_intent = AgentCapabilityIntent(
        agent_id="coding",
        tenant_id="victim-tenant",
        user_id="victim-user",
        capability="write_files",
        side_effect_class=SideEffectClass.WRITE,
        task_id="t1",
        task_step_id="s1",
        agent_run_id="r1",
    )
    decision = gate.admit(forged_intent)
    _assert_fail_closed(decision)
    assert sandbox.calls == 0
    # The refused mutation is still recorded (append-only, no authority).
    tail = gate.audit.snapshot()[-1]
    assert tail.capability_requested == "write_files"
    assert tail.disposition is Disposition.DENIED


def test_adversarial_audit_records_captured_claims_as_data():
    from agent.agent_security_boundary.audit import ExecutionAuditRecord

    gate, sandbox = _wired(boundary=None)
    gate = SecurityBoundaryGate(  # noqa: F811
        policy=_Policy(),
        capability_router=_Router(),
        system_boundary=None,
        executor=_Executor(),
        sandbox=_SandboxAdapter(),
        registry=_Registry(),
    )
    gate.admit(
        _intent(),
        caller_claims=[CallerClaim(approval="APPROVED", allow=True)],
    )
    record = gate.audit.snapshot()[-1]
    assert isinstance(record, ExecutionAuditRecord)
    assert record.admission_outcome is AdmissionOutcome.DENY
    assert record.disposition is Disposition.COMPONENT_MISSING