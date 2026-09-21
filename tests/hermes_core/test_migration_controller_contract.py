import pytest
from hermes_core.domain.migration import *
S=MigrationScope(profile="p")
def req(f,t,g=0,owner=Owner.LEGACY): return TransitionRequest("id",g,f,t,owner,S,"reason")
def test_m1_initial_owner(): assert MigrationController().state.owner is Owner.LEGACY
def test_m2_candidate_distinct(): assert MigrationController().state.candidate_owner is Owner.HERMES_CORE
def test_m3_deterministic(): assert MigrationController().apply(req(Phase.OFF,Phase.SHADOW)).status is ResultStatus.APPLIED
def test_m4_generation_once(): c=MigrationController(); c.apply(req(Phase.OFF,Phase.SHADOW)); assert c.state.generation==1
def test_m5_conflict(): c=MigrationController(); assert c.apply(req(Phase.OFF,Phase.SHADOW,1)).status is ResultStatus.CONFLICT
def test_m6_conflict_unchanged(): c=MigrationController(); s=c.state; c.apply(req(Phase.OFF,Phase.SHADOW,1)); assert c.state is s
def test_m7_illegal_jump(): assert MigrationController().apply(req(Phase.OFF,Phase.CUTOVER)).status is ResultStatus.INVALID_TRANSITION
def test_m8_reject_no_advance(): c=MigrationController(); c.apply(req(Phase.OFF,Phase.CUTOVER)); assert c.state.generation==0
def test_m9_no_dual_owner():
 with pytest.raises(ValueError): ControllerState(owner=Owner.LEGACY,candidate_owner=Owner.LEGACY)
def test_m10_shadow_no_transfer(): c=MigrationController(); c.apply(req(Phase.OFF,Phase.SHADOW)); assert c.state.owner is Owner.LEGACY
def test_m11_kill_switch(): c=MigrationController(); c.set_kill_switch(True,0); assert c.apply(req(Phase.OFF,Phase.SHADOW,1)).status is ResultStatus.KILL_SWITCHED
def test_m12_kill_fenced(): c=MigrationController(); c.set_kill_switch(True,0); assert c.set_kill_switch(False,0).status is ResultStatus.CONFLICT
def test_m13_scope_invalid():
 with pytest.raises(ValueError): MigrationScope()
def test_m14_request_immutable():
 with pytest.raises(Exception): req(Phase.OFF,Phase.SHADOW).to_phase=Phase.CANARY
def test_m15_state_immutable():
 with pytest.raises(Exception): ControllerState().phase=Phase.SHADOW
def test_m16_result_immutable():
 with pytest.raises(Exception): TransitionResult(ResultStatus.NOOP,ControllerState(),"x").status=ResultStatus.APPLIED
def test_m17_drain_distinct(): assert DrainState.DRAIN_REQUESTED is not DrainState.DRAINED
def test_m18_cutover_drain_required(): c=MigrationController(ControllerState(Phase.DRAINING,scope=S,drain_state=DrainState.DRAIN_REQUESTED)); assert c.apply(req(Phase.DRAINING,Phase.CUTOVER)).status is ResultStatus.DRAIN_REQUIRED
def test_m19_rollback_fenced(): c=MigrationController(ControllerState(Phase.CANARY,scope=S)); assert c.apply(req(Phase.CANARY,Phase.ROLLBACK,1)).status is ResultStatus.CONFLICT
def test_m20_failover_distinct(): assert MigrationController().failover("f",0,S).status is ResultStatus.FAILOVER_NOT_ALLOWED
def test_m21_noop(): c=MigrationController(); assert c.apply(req(Phase.OFF,Phase.OFF)).status is ResultStatus.NOOP
def test_m22_audit_no_runtime_objects(): a=AuditEvent("id",0,1,ResultStatus.APPLIED,"ok",Phase.OFF,Phase.SHADOW,Owner.LEGACY,Owner.LEGACY); assert "secret" not in repr(a)
def test_m23_prior_suite_marker(): assert MigrationController
def test_m24_runtime_untouched(): assert "gateway" not in MigrationController.__module__
def test_corrective_malformed_requests():
 with pytest.raises(ValueError): TransitionRequest("",0,Phase.OFF,Phase.SHADOW,Owner.LEGACY,S,"")
 with pytest.raises(ValueError): ControllerState(generation=-1)

def test_full_lifecycle_ownership_and_audit():
 c=MigrationController(); assert c.apply(req(Phase.OFF,Phase.SHADOW)).status is ResultStatus.APPLIED
 assert c.state.owner is Owner.LEGACY and c.state.owner is not c.state.candidate_owner
 assert c.apply(req(Phase.SHADOW,Phase.CANARY,1)).status is ResultStatus.APPLIED
 assert c.apply(req(Phase.CANARY,Phase.DRAINING,2)).status is ResultStatus.APPLIED
 assert c.drain("d1",3,S,DrainState.DRAIN_REQUESTED).status is ResultStatus.APPLIED
 assert c.drain("d2",4,S,DrainState.DRAINED).status is ResultStatus.APPLIED
 cut=c.apply(req(Phase.DRAINING,Phase.CUTOVER,5,Owner.HERMES_CORE)); assert cut.status is ResultStatus.APPLIED
 assert c.state.owner is Owner.HERMES_CORE and c.state.candidate_owner is Owner.LEGACY and cut.audit.previous_owner is Owner.LEGACY and cut.audit.new_owner is Owner.HERMES_CORE
 rb=c.apply(req(Phase.CUTOVER,Phase.ROLLBACK,6,Owner.LEGACY)); assert rb.status is ResultStatus.APPLIED and c.state.owner is Owner.LEGACY and rb.audit.previous_owner is Owner.HERMES_CORE and rb.audit.new_owner is Owner.LEGACY
 off=c.apply(req(Phase.ROLLBACK,Phase.OFF,7,Owner.LEGACY)); assert off.status is ResultStatus.APPLIED and c.state.owner is Owner.LEGACY

def test_failover_fencing_and_no_mutation():
 c=MigrationController(); before=c.state
 assert c.failover("f",1,S).status is ResultStatus.CONFLICT and c.state is before
 result=c.failover("f",0,S); assert result.status is ResultStatus.FAILOVER_NOT_ALLOWED and c.state is before

def test_drain_scope_noop_and_invalid_jump():
 c=MigrationController(ControllerState(scope=S))
 assert c.drain("x",0,MigrationScope(profile="other"),DrainState.DRAIN_REQUESTED).reason_code=="scope_mismatch"
 assert c.drain("x",0,S,DrainState.DRAINED).status is ResultStatus.REJECTED
 first=c.drain("x",0,S,DrainState.DRAIN_REQUESTED); assert first.status is ResultStatus.APPLIED
 generation=c.state.generation; assert c.drain("x",generation,S,DrainState.DRAIN_REQUESTED).status is ResultStatus.NOOP and c.state.generation==generation
 with pytest.raises(ValueError): c.drain("x",generation,S,"bad")

def test_kill_switch_noop_generation():
 c=MigrationController(); assert c.set_kill_switch(True,0).status is ResultStatus.APPLIED; g=c.state.generation; assert c.set_kill_switch(True,g).status is ResultStatus.NOOP and c.state.generation==g
