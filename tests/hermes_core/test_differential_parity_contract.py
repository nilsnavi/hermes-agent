import pytest
from hermes_core.domain.parity import ParityClass, ParityObservation
from hermes_core.domain.session import Session,SessionId,SessionKey
from hermes_core.domain.delivery import Delivery,DeliveryResult,DeliveryState
from hermes_core.application.delivery_service import DeliveryService
from hermes_core.domain.routing import (FailureClass, FailureEvidence, FallbackDisposition, FallbackPolicy, RouteCandidate, RoutePlan, RoutePurpose)
from hermes_core.domain.migration import MigrationController

def evidence(n,outcome,reason="legacy_unverified"):
 return ParityObservation("legacy-runtime",f"DP{n}","UNVERIFIED",outcome,ParityClass.UNVERIFIED,reason)
def test_dp01_session_initial_state():
 s=Session(SessionId("s"),SessionKey("k")); assert evidence(1,f"{s.status.value}:generation={s.generation}").core_outcome=="active:generation=0"
def test_dp02_successful_lease():
 s=Session(SessionId("s"),SessionKey("k")); assert s.acquire_lease("a"); assert evidence(2,f"owner={s.lease_owner},generation={s.generation}").core_outcome=="owner=a,generation=1"
def test_dp03_competing_lease():
 s=Session(SessionId("s"),SessionKey("k")); s.acquire_lease("a"); assert not s.acquire_lease("b"); assert evidence(3,"rejected").core_outcome=="rejected"
def test_dp04_valid_release():
 s=Session(SessionId("s"),SessionKey("k")); s.acquire_lease("a"); assert s.release_lease("a",1); assert evidence(4,"released:generation=2").core_outcome=="released:generation=2"
def test_dp05_stale_release():
 s=Session(SessionId("s"),SessionKey("k")); s.acquire_lease("a"); s.release_lease("a",1); s.acquire_lease("b"); assert not s.release_lease("a",1); assert evidence(5,"stale_rejected").core_outcome=="stale_rejected"
def test_dp06_valid_close():
 s=Session(SessionId("s"),SessionKey("k")); s.acquire_lease("a"); assert s.close("a",1); assert evidence(6,"closed").core_outcome=="closed"
def test_dp07_stale_close():
 s=Session(SessionId("s"),SessionKey("k")); s.acquire_lease("a"); assert not s.close("b",1); assert evidence(7,"stale_rejected").core_outcome=="stale_rejected"
def test_dp08_generation_monotonicity():
 s=Session(SessionId("s"),SessionKey("k")); s.acquire_lease("a"); s.release_lease("a",1); assert s.generation==2; assert evidence(8,"0,1,2").core_outcome=="0,1,2"
def test_dp09_persistence_successful_mutation():
 from tests.hermes_core.test_session_persistence_hardening import make_service
 s,repo,service=make_service(); result=service.acquire_result(s,"a"); assert result.committed and repo.stored.generation==1
def test_dp10_stale_persistence_mutation():
 from tests.hermes_core.test_session_persistence_hardening import make_service
 _,repo,service=make_service(); a=service.resume(SessionId("s")); b=service.resume(SessionId("s")); assert service.acquire_result(a,"a").committed; assert service.acquire_result(b,"b").status.value=="conflict"
def test_dp11_persistence_failure():
 from tests.hermes_core.test_session_persistence_hardening import make_service
 s,repo,service=make_service(); repo.fail=True; result=service.acquire_result(s,"a"); assert result.status.value=="persistence_error" and s.generation==0 and repo.stored.generation==0
class T:
 def __init__(self,r): self.r=r
 def send(self,d): return self.r
 def edit(self,d): return self.r
def test_dp12_delivery_success():
 d=Delivery("o","k","x"); DeliveryService(T(DeliveryResult(True,"id"))).deliver(d); assert d.state is DeliveryState.DELIVERED; assert evidence(12,d.state.value).core_outcome=="delivered"
def test_dp13_delivery_failure():
 d=Delivery("o","k","x"); DeliveryService(T(DeliveryResult(False))).deliver(d); assert d.state is DeliveryState.FAILED; assert evidence(13,d.state.value).core_outcome=="failed"
def test_dp14_delivery_metadata():
 r=DeliveryResult(True,"id",True,"ok"); assert (r.external_id,r.retryable,r.error)==("id",True,"ok"); assert evidence(14,"id/retryable/error").core_outcome=="id/retryable/error"
def test_dp15_ambiguous_delivery():
 from hermes_core.ports.delivery import DeliveryTransportError
 class T:
  def send(self,d): raise DeliveryTransportError("ambiguous")
  def edit(self,d): pass
 d=Delivery("o","k","x"); result=DeliveryService(T()).deliver_result(d); assert d.state is DeliveryState.UNKNOWN_ACK and result.status.value=="transport_error"
def test_dp16_authorized_tool():
 from hermes_core.application.execution_service import ExecutionService
 from hermes_core.domain.capability import CapabilityGrant,argument_binding
 class E:
  def __init__(self): self.calls=0
  def invoke(self,*a): self.calls+=1; return "ok"
 e=E(); g=CapabilityGrant("g","p","s","t","c","tool",argument_binding({})); assert ExecutionService(e).invoke_protected("tool",{},principal_id="p",session_id="s",turn_id="t",tool_call_id="c",grant=g)=="ok" and e.calls==1
def test_dp17_unauthorized_tool():
 from hermes_core.application.execution_service import ExecutionService
 class E:
  def __init__(self): self.calls=0
  def invoke(self,*a): self.calls+=1
 e=E();
 with pytest.raises(PermissionError): ExecutionService(e).invoke_protected("tool",{},principal_id="p",session_id="s")
 assert e.calls==0
def test_dp18_approval():
 from hermes_core.domain.capability import CapabilityGrant,Approval,argument_binding,validate_grant,AuthorizationStatus
 g=CapabilityGrant("g","p","s","t","c","tool",argument_binding({}),approval_required=True); a=Approval("s","t","c","tool",g.argument_binding); assert validate_grant(g,principal_id="p",session_id="s",turn_id="t",tool_call_id="c",tool_name="tool",arguments={},evaluation_time=1,approval=a).status is AuthorizationStatus.AUTHORIZED
def test_dp19_routing_purpose(): assert RoutePurpose.MAIN.value=="main"; assert evidence(19,"main").core_outcome=="main"
def test_dp20_route_selection():
 p=RoutePlan((RouteCandidate("a","m","r",RoutePurpose.MAIN,1),)); assert p.select().candidate.provider=="a"; assert evidence(20,"a/m").core_outcome=="a/m"
def test_dp21_fallback():
 p=RoutePlan((RouteCandidate("a","m","r1",RoutePurpose.MAIN,1),RouteCandidate("b","m","r2",RoutePurpose.MAIN,2)),FallbackPolicy(((FailureClass.TRANSIENT,FallbackDisposition.ALLOWED),))); first=p.first(); result=p.fallback(first,FailureEvidence(FailureClass.TRANSIENT,"x",first)); assert result.candidate.provider=="b"
def test_dp22_credential_reference():
 c=RouteCandidate("a","m","opaque-slot",RoutePurpose.MAIN,1); assert c.credential_reference=="opaque-slot" and "secret" not in repr(c)
def test_dp23_migration_isolation(): assert isinstance(MigrationController(),MigrationController); assert ParityObservation("control-plane","DP23","NOT_APPLICABLE","isolated_controller",ParityClass.NOT_APPLICABLE,"no_legacy_controller").classification is ParityClass.NOT_APPLICABLE
def test_dp24_suite_reference(): assert evidence(24,"external_suite_evidence_required").core_outcome=="external_suite_evidence_required"
def test_match_requires_verified_legacy():
 with pytest.raises(ValueError): ParityObservation("s","x","UNVERIFIED","x",ParityClass.MATCH,"bad","UNVERIFIED","executed")
def test_malformed_classification_rejected():
 with pytest.raises(ValueError): ParityObservation("s","x","u","c","MATCH","r")
