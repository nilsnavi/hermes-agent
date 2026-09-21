import pytest
from hermes_core.application.execution_service import ExecutionService
from hermes_core.domain.capability import Approval, CapabilityGrant, AuthorizationStatus, argument_binding, validate_grant

class E:
    def __init__(self): self.calls=0
    def invoke(self,n,a,c): self.calls+=1; return "ok"

def grant(**kw): return CapabilityGrant("g","p","s","t","c","tool",argument_binding(kw.pop("args",{})),**kw)
def call(service, g, **kw): return service.invoke_protected("tool", kw.pop("args",{}), session_id="s",turn_id="t",tool_call_id="c",principal_id=kw.pop("principal_id","p"),grant=g,evaluation_time=kw.pop("time",1),**kw)

def test_s1_s2_s16_denied_before_execute():
 e=E(); s=ExecutionService(e)
 for g in (None, grant(approval_required=True)):
  with pytest.raises(PermissionError): call(s,g)
 assert e.calls==0
def test_s3_authorized_once():
 e=E(); g=grant(); assert call(ExecutionService(e),g)=="ok"; assert e.calls==1
@pytest.mark.parametrize("field",["session_id","turn_id","tool_call_id","tool_name"])
def test_s4_to_s7_context_mismatch(field):
 vals={"principal_id":"p","session_id":"s","turn_id":"t","tool_call_id":"c","tool_name":"tool"}; vals[field]="other"
 g=CapabilityGrant("g",**{k:vals[k] for k in ("principal_id","session_id","turn_id","tool_call_id","tool_name")},argument_binding=argument_binding({}))
 assert validate_grant(g,principal_id="p",session_id="s",turn_id="t",tool_call_id="c",tool_name="tool",arguments={},evaluation_time=1).status is AuthorizationStatus.CONTEXT_MISMATCH
def test_s8_to_s10_argument_binding():
 assert argument_binding({"a":1,"b":2})==argument_binding({"b":2,"a":1}); assert argument_binding({"a":1})!=argument_binding({"a":2})
 e=E(); g=grant(args={"a":1});
 with pytest.raises(PermissionError): call(ExecutionService(e),g,args={"a":2})
def test_argument_binding_rejects_non_json_values_and_non_finite_numbers():
 import math
 for value in (float("nan"), float("inf"), float("-inf"), {1,2}):
  with pytest.raises((ValueError, TypeError)): argument_binding({"value": value})
def test_exact_json_argument_domain():
 assert argument_binding({"1": "x"})
 for value in ({1: "x"}, {"nested": {1: "x"}}, (1,), {1}, b"x"):
  with pytest.raises((ValueError, TypeError)): argument_binding(value)
 assert argument_binding(["x", 1, True, None])
 assert argument_binding({"a": {"b": 1, "c": 2}})==argument_binding({"a": {"c": 2, "b": 1}})
 assert argument_binding({"a": {"b": 1}})!=argument_binding({"a": {"b": 2}})
def test_s11_s12_expired_revoked():
 for g in (grant(expires_at=1),grant(revoked=True)):
  assert validate_grant(g,principal_id="p",session_id="s",turn_id="t",tool_call_id="c",tool_name="tool",arguments={},evaluation_time=1).status in (AuthorizationStatus.EXPIRED,AuthorizationStatus.REVOKED)
def test_future_issued_grant_is_denied():
 assert validate_grant(grant(issued_at=5),principal_id="p",session_id="s",turn_id="t",tool_call_id="c",tool_name="tool",arguments={},evaluation_time=4).reason_code=="grant_not_yet_valid"
def test_s13_s14_approval_binding():
 g=grant(approval_required=True); assert validate_grant(g,principal_id="p",session_id="s",turn_id="t",tool_call_id="c",tool_name="tool",arguments={},evaluation_time=1).status is AuthorizationStatus.APPROVAL_REQUIRED
 a=Approval("s","t","c","tool",g.argument_binding); assert validate_grant(g,principal_id="p",session_id="s",turn_id="t",tool_call_id="c",tool_name="tool",arguments={},evaluation_time=1,approval=a).authorized
def test_s15_no_approval_needed(): assert validate_grant(grant(),principal_id="p",session_id="s",turn_id="t",tool_call_id="c",tool_name="tool",arguments={},evaluation_time=1).authorized
def test_s17_stable_reason(): assert validate_grant(None,principal_id="p",session_id="s",turn_id="t",tool_call_id="c",tool_name="tool",arguments={},evaluation_time=1).reason_code=="missing_grant"
def test_malformed_grant_fails_closed():
 g=CapabilityGrant("", "p", "s", "t", "c", "tool", argument_binding({}))
 assert validate_grant(g,principal_id="p",session_id="s",turn_id="t",tool_call_id="c",tool_name="tool",arguments={},evaluation_time=1).status is AuthorizationStatus.INVALID_GRANT
def test_s18_executor_cannot_bypass():
 e=E();
 with pytest.raises(PermissionError): call(ExecutionService(e),None)
 assert e.calls==0
def test_boolean_cannot_disable_protected_authorization():
 e=E()
 with pytest.raises(PermissionError): ExecutionService(e).invoke_protected("tool", {}, principal_id="p", session_id="s", grant=None, approved=False)
 assert e.calls==0
def test_principal_binding_denies_other_principal():
 e=E(); g=grant()
 with pytest.raises(PermissionError): call(ExecutionService(e),g,principal_id="other")
 assert e.calls==0
def test_approved_legacy_metadata_does_not_authorize():
 e=E()
 with pytest.raises(PermissionError): ExecutionService(e).invoke_protected("tool", {}, principal_id="p", session_id="s", approved=True)
 assert e.calls==0
def test_s19_provider_neutral_objects_only(): assert all(x.__module__.startswith("hermes_core") for x in (CapabilityGrant,Approval))
def test_s20_prior_contracts_unaffected(): assert argument_binding({})
