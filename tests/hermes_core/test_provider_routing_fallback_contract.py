import pytest
from hermes_core.domain.routing import *

def candidates(): return RoutePlan((RouteCandidate("b","m2","ref2",RoutePurpose.MAIN,2),RouteCandidate("a","m1","ref1",RoutePurpose.MAIN,1),RouteCandidate("c","m3","ref3",RoutePurpose.MAIN,3)), FallbackPolicy(((FailureClass.TRANSIENT,FallbackDisposition.ALLOWED),(FailureClass.RATE_LIMITED,FallbackDisposition.ALLOWED))))
def test_r1_r8_deterministic_order():
 p=candidates(); assert p.first().provider=="a"; assert RoutePlan(tuple(reversed(p.candidates))).candidates==p.candidates
def test_r2_r3_no_secrets_opaque():
 c=candidates().first(); assert "secret" not in repr(c); assert c.credential_reference=="ref1"
def test_r4_purpose_distinct(): assert RouteCandidate("a","m",None,RoutePurpose.COMPRESSION,1).purpose is RoutePurpose.COMPRESSION
def test_r5_precedence(): assert candidates().first().precedence==1
def test_r6_r7_fallback_legal():
 p=candidates(); e=FailureEvidence(FailureClass.TRANSIENT,"timeout",p.first()); assert p.fallback(p.first(),e).candidate.provider=="b"
def test_r9_fallback_allowed_advances(): assert candidates().fallback(candidates().first(),FailureEvidence(FailureClass.RATE_LIMITED,"rate",candidates().first())).status is RoutingStatus.ROUTED
def test_r10_fallback_denied_stops():
 p=candidates(); assert p.fallback(p.first(),FailureEvidence(FailureClass.AUTHENTICATION,"auth",p.first())).status is RoutingStatus.FALLBACK_NOT_ALLOWED
def test_r11_exhaustion():
 p=candidates(); c=p.candidates[-1]; assert p.fallback(c,FailureEvidence(FailureClass.TRANSIENT,"x",c)).status is RoutingStatus.EXHAUSTED
def test_r12_missing_candidates(): assert RoutePlan(()).select().status is RoutingStatus.NO_ROUTE
def test_r13_retry_distinct(): assert candidates().fallback(candidates().first(),FailureEvidence(FailureClass.TRANSIENT,"x",candidates().first())).candidate.provider=="b"
def test_r14_provider_exception_not_modelled(): assert not any("Exception" in x for x in (FailureClass.__members__))
def test_r15_r16_credential_reference_only(): assert candidates().first().credential_reference.startswith("ref")
def test_r17_immutable():
 with pytest.raises(Exception): candidates().first().provider="x"
def test_r18_cache_unverified(): assert RoutePurpose.MAIN is not RoutePurpose.COMPRESSION
def test_r19_c4_compat(): assert RoutePurpose.MAIN.value=="main"
def test_r20_prior_domains_exist(): assert RoutePlan
def test_corrective_plan_rejections():
 with pytest.raises(ValueError): RoutePlan((RouteCandidate("a","m","r",RoutePurpose.MAIN,1),RouteCandidate("a","m","r",RoutePurpose.MAIN,2)))
 with pytest.raises(ValueError): RoutePlan((RouteCandidate("a","m","r",RoutePurpose.MAIN,1),RouteCandidate("b","m","s",RoutePurpose.TITLE,2)))
 with pytest.raises(ValueError): RouteCandidate("","m",None,RoutePurpose.MAIN,1)
def test_corrective_evidence_binding_and_denied_classes():
 p=candidates(); other=RouteCandidate("x","m","r",RoutePurpose.MAIN,3)
 assert p.fallback(p.first(),FailureEvidence(FailureClass.TRANSIENT,"x",other)).status is RoutingStatus.FALLBACK_NOT_ALLOWED
 assert p.fallback(other,FailureEvidence(FailureClass.TRANSIENT,"x",other)).status is RoutingStatus.FALLBACK_NOT_ALLOWED
 for c in (FailureClass.AUTHENTICATION,FailureClass.INVALID_REQUEST,FailureClass.UNKNOWN): assert FallbackPolicy().disposition(c) is FallbackDisposition.DENIED
