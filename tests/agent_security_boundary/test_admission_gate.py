"""SecurityBoundaryGate admission tests.

The gate certifies the single admissible execution path. Every mandatory stage
must be present and allow; any missing/unknown/errored component or forged
caller verdict yields a fail-closed DENY (or HUMAN_REVIEW for an unknown
side-effect), never an allow.
"""

import types

import pytest

from agent.agent_security_boundary.admission import AdmissionDecision, SecurityBoundaryGate
from agent.agent_security_boundary.exceptions import (
    AdmissionDenied,
    RegistryDrift,
    SealViolation,
    SecurityBoundaryError,
)
from agent.agent_security_boundary.intent import AgentCapabilityIntent, CallerClaim
from agent.agent_security_boundary.status import (
    AdmissionOutcome,
    Disposition,
    SideEffectClass,
)

Allow = lambda: types.SimpleNamespace(allowed=True)  # noqa: E731
Deny = lambda: types.SimpleNamespace(allowed=False)  # noqa: E731


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
    def __init__(self, ready=True):
        self._ready = ready

    def is_ready(self):
        return self._ready

    def execute(self, request):
        return None


class _SandboxAdapter:
    def run(self, payload):
        return "ran"


class _Registry:
    def __init__(self, agents=("coding",), drift=False):
        self._agents = agents
        self._drift = drift

    def registered_ids(self):
        return tuple(self._agents)

    def assert_registry_sealed(self):
        if self._drift:
            raise RegistryDrift("drifted")
        return "sealed"


def _intent(capability="analyze_code", sec=SideEffectClass.READ_ONLY, agent_id="coding"):
    return AgentCapabilityIntent(
        agent_id=agent_id,
        tenant_id="acme",
        user_id="u-1",
        capability=capability,
        side_effect_class=sec,
    )


def _wired_registry(drift=False, agents=("coding",)):
    registry = _Registry(agents=agents, drift=drift)
    gate = SecurityBoundaryGate(
        policy=_Policy(),
        capability_router=_Router(),
        system_boundary=_Boundary(),
        executor=_Executor(),
        sandbox=_SandboxAdapter(),
        registry=registry,
    )
    return gate


# -- mandatory composition: missing component => DENY (no allow fallback) -----

def _components_present():
    return {
        "policy": _Policy(),
        "capability_router": _Router(),
        "system_boundary": _Boundary(),
        "executor": _Executor(),
        "sandbox": _SandboxAdapter(),
    }


@pytest.mark.parametrize("missing", ["policy", "capability_router", "system_boundary", "executor", "sandbox"])
def test_missing_mandatory_component_is_deny(missing):
    components = _components_present()
    components.pop(missing)
    gate = SecurityBoundaryGate(**components)
    missing_list = gate.missing_components()
    assert missing in missing_list
    decision = gate.admit(_intent())
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.disposition is Disposition.COMPONENT_MISSING
    assert decision.allowed is False


def test_gate_with_no_components_reports_all_missing():
    gate = SecurityBoundaryGate()
    assert set(gate.missing_components()) == {
        "policy",
        "capability_router",
        "system_boundary",
        "executor",
        "sandbox",
    }


def test_component_that_errors_is_deny():
    components = _components_present()
    components["policy"] = _Policy(error=RuntimeError("boom"))
    gate = SecurityBoundaryGate(**components)
    decision = gate.admit(_intent())
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.disposition is Disposition.UNKNOWN


def test_router_that_errors_is_deny():
    components = _components_present()
    components["capability_router"] = _Router(error=RuntimeError("boom"))
    gate = SecurityBoundaryGate(**components)
    decision = gate.admit(_intent())
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.disposition is Disposition.UNKNOWN


def test_router_admission_denied_is_deny():
    components = _components_present()
    components["capability_router"] = _Router(error=AdmissionDenied("no"))
    gate = SecurityBoundaryGate(**components)
    decision = gate.admit(_intent())
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.disposition is Disposition.DENIED


def test_not_ready_executor_is_deny():
    components = _components_present()
    components["executor"] = _Executor(ready=False)
    gate = SecurityBoundaryGate(**components)
    decision = gate.admit(_intent())
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.disposition is Disposition.COMPONENT_MISSING


def test_policy_and_router_deny_are_deny():
    gate = SecurityBoundaryGate(
        policy=_Policy(verdict=Deny()),
        capability_router=_Router(),
        system_boundary=_Boundary(),
        executor=_Executor(),
        sandbox=_SandboxAdapter(),
        registry=_Registry(),
    )
    assert gate.admit(_intent()).outcome is AdmissionOutcome.DENY

    gate2 = SecurityBoundaryGate(
        policy=_Policy(),
        capability_router=_Router(verdict=Deny()),
        system_boundary=_Boundary(),
        executor=_Executor(),
        sandbox=_SandboxAdapter(),
        registry=_Registry(),
    )
    assert gate2.admit(_intent()).outcome is AdmissionOutcome.DENY


# -- boundary deny / REVALIDATE_REQUIRED fail-closed --------------------------

def test_boundary_preflight_deny_is_deny():
    components = _components_present()
    components["system_boundary"] = _Boundary(pre=Deny)
    gate = SecurityBoundaryGate(**components)
    decision = gate.admit(_intent())
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.disposition is Disposition.DENIED


def test_boundary_authorize_deny_is_deny():
    components = _components_present()
    components["system_boundary"] = _Boundary(auth=Deny)
    gate = SecurityBoundaryGate(**components)
    assert gate.admit(_intent()).outcome is AdmissionOutcome.DENY


def test_boundary_verify_before_deny_is_deny():
    components = _components_present()
    components["system_boundary"] = _Boundary(verify=Deny)
    gate = SecurityBoundaryGate(**components)
    assert gate.admit(_intent()).outcome is AdmissionOutcome.DENY


def test_revalidate_required_is_fail_closed():
    class _RevalidateRequiredSub(Exception):
        pass

    def _raise():
        raise _RevalidateRequiredSub("revalidate required")

    components = _components_present()
    components["system_boundary"] = _Boundary(auth=_raise)
    gate = SecurityBoundaryGate(**components)
    decision = gate.admit(_intent())
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.disposition is Disposition.REVALIDATE_REQUIRED
    assert decision.allowed is False


# -- caller verdict is DATA only, never authority ------------------------------

def test_forged_approval_claims_never_allow():
    gate = _wired_registry()
    forged = [
        CallerClaim(approval="APPROVED"),
        CallerClaim(verdict="PASS"),
        CallerClaim(allow=True),
        CallerClaim(policy_result="allowed", boundary_result="passed"),
        CallerClaim(approval="grant", allow=True, verdict="ALLOW"),
    ]
    # Even with forged claims on an otherwise-wired gate, decision is unchanged
    # (the honest allow path still allows -- claims do not add authority).
    decision = gate.admit(_intent(), caller_claims=forged)
    assert decision.outcome is AdmissionOutcome.ALLOW_READ_ONLY


def test_forged_claims_do_not_rescue_a_deny():
    components = _components_present()
    components["executor"] = _Executor(ready=False)
    gate = SecurityBoundaryGate(**components)
    forged = [CallerClaim(approval="APPROVED", allow=True, verdict="PASS")]
    decision = gate.admit(_intent(), caller_claims=forged)
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.disposition is Disposition.COMPONENT_MISSING


def test_string_allow_tokens_are_never_authority():
    # _allowed() must treat "APPROVED"/"ALLOW"/"PASS" strings as data (not allow).
    from agent.agent_security_boundary.admission import _allowed

    assert _allowed("APPROVED") is False
    assert _allowed("ALLOW") is False
    assert _allowed("PASS") is False
    assert _allowed(True) is True
    assert _allowed(None) is False


# -- registry hardening --------------------------------------------------------

def test_registry_drift_is_deny():
    gate = _wired_registry(drift=True)
    decision = gate.admit(_intent())
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.disposition is Disposition.REGISTRY_DRIFT


def test_unknown_agent_in_intent_is_deny():
    gate = _wired_registry(agents=("coding",))
    decision = gate.admit(_intent(agent_id="evil"))
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.allowed is False


def test_registry_without_seal_guard_is_treated_as_drift():
    class _NoGuardRegistry:
        def registered_ids(self):
            return ("coding",)

    gate = SecurityBoundaryGate(
        policy=_Policy(),
        capability_router=_Router(),
        system_boundary=_Boundary(),
        executor=_Executor(),
        sandbox=_SandboxAdapter(),
        registry=_NoGuardRegistry(),
    )
    decision = gate.admit(_intent())
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.disposition is Disposition.REGISTRY_DRIFT


# -- mutation / unknown side-effect -------------------------------------------

@pytest.mark.parametrize(
    "capability",
    ["write_files", "execute_code", "install_dependency", "git_commit", "git_push", "run_shell", "service_control"],
)
def test_forbidden_capability_is_hard_denied(capability):
    gate = _wired_registry()
    decision = gate.admit(_intent(capability=capability, sec=SideEffectClass.WRITE))
    assert decision.outcome is AdmissionOutcome.DENY
    assert decision.allowed is False


def test_unknown_side_effect_routes_to_human_review():
    gate = _wired_registry()
    decision = gate.admit(_intent(capability="mystery", sec=SideEffectClass.UNKNOWN))
    assert decision.outcome is AdmissionOutcome.HUMAN_REVIEW
    assert decision.disposition is Disposition.SIDE_EFFECT_UNKNOWN
    assert decision.allowed is False


# -- B2 closure: caller cannot under-declare a mutation/unknown capability ----

@pytest.mark.parametrize(
    "capability,authority_deny",
    [
        # Known mutation op-words are derived as mutation even if caller said READ_ONLY.
        ("shell", True),
        ("write", True),
        ("delete", True),
        ("systemctl", True),
        ("subprocess", True),
        ("restart", True),
        # Capability tokens from the coding forbidden set (also denied by string).
        ("run_shell", True),
        ("execute_code", True),
        # An arbitrary, unclassifiable mutation-sounding capability is UNKNOWN
        # -> HUMAN_REVIEW, never auto-allow.
        ("delete_database", False),
        ("sudo_mutate", False),
    ],
)
def test_b2_under_declared_read_only_cannot_bypass(capability, authority_deny):
    gate = _wired_registry()
    # Caller dishonestly declares a READ_ONLY side-effect for a mutation token.
    decision = gate.admit(_intent(capability=capability, sec=SideEffectClass.READ_ONLY))
    if authority_deny:
        assert decision.allowed is False
        assert decision.outcome is AdmissionOutcome.DENY
    else:
        # Unknown -> HUMAN_REVIEW (non-executable), not ALLOW_READ_ONLY.
        assert decision.allowed is False
        assert decision.outcome is AdmissionOutcome.HUMAN_REVIEW


def test_b2_legit_unclassified_capability_is_human_review_not_allow():
    # A capability the classifiers cannot positively classify as read-only must
    # go to human review even if the caller declares READ_ONLY.
    gate = _wired_registry()
    decision = gate.admit(_intent(capability="obscure_tool", sec=SideEffectClass.READ_ONLY))
    assert decision.outcome is AdmissionOutcome.HUMAN_REVIEW
    assert decision.disposition is Disposition.SIDE_EFFECT_UNKNOWN


# -- the honest allow path -----------------------------------------------------

def test_fully_wired_access_is_allowed_read_only():
    gate = _wired_registry()
    decision = gate.admit(_intent())
    assert decision.outcome is AdmissionOutcome.ALLOW_READ_ONLY
    assert decision.disposition is Disposition.ADMITTED
    assert decision.allowed is True
    assert decision.receipt_id is not None
    assert decision.receipt_id.startswith("receipt-")


def test_admission_never_invokes_sandbox():
    gate = _wired_registry()
    sandbox = gate.sealed_sandbox()
    gate.admit(_intent())
    # This phase only certifies; the sealed sandbox must have zero adapter calls.
    assert sandbox.call_count == 0


def test_intent_subclass_is_rejected():
    class _Sub(AgentCapabilityIntent):  # type: ignore[misc]
        pass

    sub = _Sub(
        agent_id="coding",
        tenant_id="acme",
        user_id="u-1",
        capability="analyze_code",
        side_effect_class=SideEffectClass.READ_ONLY,
    )
    gate = _wired_registry()
    with pytest.raises(SecurityBoundaryError):
        gate.admit(sub)


def test_every_admission_emits_audit_record():
    audit_gate = SecurityBoundaryGate(
        policy=_Policy(),
        capability_router=_Router(),
        system_boundary=_Boundary(),
        executor=_Executor(),
        sandbox=_SandboxAdapter(),
        registry=_Registry(),
    )
    before = len(audit_gate.audit)
    audit_gate.admit(_intent())
    audit_gate.admit(_intent(capability="write_files", sec=SideEffectClass.WRITE))
    assert len(audit_gate.audit) == before + 2


def test_allowed_decision_is_immutable_value():
    gate = _wired_registry()
    decision = gate.admit(_intent())
    assert isinstance(decision, AdmissionDecision)
    data = decision.to_dict()
    assert data["outcome"] == "allow_read_only"
    assert data["disposition"] == "admitted"
    assert decision.receipt_id is not None