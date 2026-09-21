"""Control-plane migration contract; no runtime side effects."""
from dataclasses import dataclass
from enum import Enum

class Phase(str, Enum): OFF="off"; SHADOW="shadow"; CANARY="canary"; DRAINING="draining"; CUTOVER="cutover"; ROLLBACK="rollback"
class Owner(str, Enum): LEGACY="legacy"; HERMES_CORE="hermes_core"
class DrainState(str, Enum): NOT_DRAINING="not_draining"; DRAIN_REQUESTED="drain_requested"; DRAINED="drained"
class ResultStatus(str, Enum): APPLIED="applied"; NOOP="noop"; REJECTED="rejected"; CONFLICT="conflict"; KILL_SWITCHED="kill_switched"; INVALID_TRANSITION="invalid_transition"; DRAIN_REQUIRED="drain_required"; FAILOVER_NOT_ALLOWED="failover_not_allowed"
@dataclass(frozen=True)
class MigrationScope:
 profile:str|None=None; session_key:str|None=None
 def __post_init__(self):
  if not isinstance(self.profile,(str,type(None))) or not isinstance(self.session_key,(str,type(None))) or not any(v and v.strip() for v in (self.profile,self.session_key)): raise ValueError("scope_invalid")
@dataclass(frozen=True)
class ControllerState:
 phase:Phase=Phase.OFF; owner:Owner=Owner.LEGACY; candidate_owner:Owner=Owner.HERMES_CORE; generation:int=0; kill_switch_enabled:bool=False; drain_state:DrainState=DrainState.NOT_DRAINING; scope:MigrationScope|None=None; previous_owner:Owner=Owner.LEGACY
 def __post_init__(self):
  if not isinstance(self.phase,Phase) or not isinstance(self.owner,Owner) or not isinstance(self.candidate_owner,Owner) or not isinstance(self.drain_state,DrainState) or not isinstance(self.kill_switch_enabled,bool): raise ValueError("state_invalid")
  if not isinstance(self.generation,int) or isinstance(self.generation,bool) or self.generation<0: raise ValueError("generation_invalid")
  if self.scope is not None and not isinstance(self.scope,MigrationScope): raise ValueError("scope_invalid")
  if self.owner is self.candidate_owner: raise ValueError("dual_authoritative_owner")
@dataclass(frozen=True)
class TransitionRequest:
 transition_id:str; expected_generation:int; from_phase:Phase; to_phase:Phase; requested_owner:Owner; scope:MigrationScope; reason_code:str
 def __post_init__(self):
  if not all(isinstance(x,str) and x.strip() for x in (self.transition_id,self.reason_code)): raise ValueError("request_invalid")
  if not isinstance(self.expected_generation,int) or isinstance(self.expected_generation,bool) or self.expected_generation<0: raise ValueError("generation_invalid")
  if not isinstance(self.from_phase,Phase) or not isinstance(self.to_phase,Phase) or not isinstance(self.requested_owner,Owner) or not isinstance(self.scope,MigrationScope): raise ValueError("request_invalid")
@dataclass(frozen=True)
class AuditEvent:
 transition_id:str; previous_generation:int; new_generation:int; status:ResultStatus; reason_code:str; from_phase:Phase; to_phase:Phase; previous_owner:Owner; new_owner:Owner
@dataclass(frozen=True)
class TransitionResult:
 status:ResultStatus; state:ControllerState; reason_code:str; audit:AuditEvent
class MigrationController:
 def __init__(self,state=None): self.state=state or ControllerState()
 def _result(self,r,request,status,reason,new=None):
  s=self.state if new is None else new; self.state=s; return TransitionResult(status,s,reason,AuditEvent(request.transition_id,r.generation,s.generation,status,reason,r.phase,s.phase,r.owner,s.owner))
 def apply(self,request):
  r=self.state
  if request.expected_generation!=r.generation: return self._result(r,request,ResultStatus.CONFLICT,"generation_conflict")
  if request.from_phase is not r.phase: return self._result(r,request,ResultStatus.REJECTED,"from_phase_mismatch")
  if request.scope!=r.scope and r.scope is not None: return self._result(r,request,ResultStatus.REJECTED,"scope_mismatch")
  if request.to_phase is r.phase: return self._result(r,request,ResultStatus.NOOP,"already_in_state")
  if r.kill_switch_enabled: return self._result(r,request,ResultStatus.KILL_SWITCHED,"kill_switch_enabled")
  legal={Phase.OFF:(Phase.SHADOW,),Phase.SHADOW:(Phase.CANARY,),Phase.CANARY:(Phase.DRAINING,Phase.ROLLBACK),Phase.DRAINING:(Phase.CUTOVER,Phase.ROLLBACK),Phase.CUTOVER:(Phase.ROLLBACK,),Phase.ROLLBACK:(Phase.OFF,)}
  if request.to_phase not in legal.get(r.phase,()): return self._result(r,request,ResultStatus.INVALID_TRANSITION,"invalid_transition")
  if request.to_phase is Phase.CUTOVER and r.drain_state is not DrainState.DRAINED: return self._result(r,request,ResultStatus.DRAIN_REQUIRED,"drain_required")
  expected=Owner.HERMES_CORE if request.to_phase is Phase.CUTOVER else Owner.LEGACY
  if request.requested_owner is not expected: return self._result(r,request,ResultStatus.REJECTED,"owner_mismatch")
  new_owner = expected if request.to_phase is Phase.CUTOVER else Owner.LEGACY
  new_candidate = Owner.LEGACY if request.to_phase is Phase.CUTOVER else Owner.HERMES_CORE
  new=ControllerState(request.to_phase,new_owner,new_candidate,r.generation+1,False,r.drain_state,request.scope,r.owner)
  return self._result(r,request,ResultStatus.APPLIED,"applied",new)
 def drain(self,transition_id,expected,scope,state):
  if not isinstance(state,DrainState): raise ValueError("drain_state_invalid")
  if self.state.scope is not None and scope != self.state.scope:
   req=TransitionRequest(transition_id,expected,self.state.phase,self.state.phase,self.state.owner,self.state.scope,"drain")
   return self._result(self.state,req,ResultStatus.REJECTED,"scope_mismatch")
  req=TransitionRequest(transition_id,expected,self.state.phase,self.state.phase,self.state.owner,scope,"drain")
  if expected!=self.state.generation:return self._result(self.state,req,ResultStatus.CONFLICT,"generation_conflict")
  if state is self.state.drain_state:return self._result(self.state,req,ResultStatus.NOOP,"already_in_state")
  allowed={(DrainState.NOT_DRAINING,DrainState.DRAIN_REQUESTED),(DrainState.DRAIN_REQUESTED,DrainState.DRAINED)}
  if (self.state.drain_state,state) not in allowed:return self._result(self.state,req,ResultStatus.REJECTED,"invalid_drain_transition")
  new=ControllerState(self.state.phase,self.state.owner,self.state.candidate_owner,self.state.generation+1,self.state.kill_switch_enabled,state,self.state.scope,self.state.previous_owner)
  return self._result(self.state,req,ResultStatus.APPLIED,"drain_updated",new)
 def set_kill_switch(self,enabled,expected,transition_id="kill-switch"):
  req=TransitionRequest(transition_id,expected,self.state.phase,self.state.phase,self.state.owner,self.state.scope or MigrationScope(profile="global"),"kill_switch")
  if expected!=self.state.generation:return self._result(self.state,req,ResultStatus.CONFLICT,"generation_conflict")
  if enabled==self.state.kill_switch_enabled:return self._result(self.state,req,ResultStatus.NOOP,"already_in_state")
  new=ControllerState(self.state.phase,self.state.owner,self.state.candidate_owner,self.state.generation+1,enabled,self.state.drain_state,self.state.scope,self.state.previous_owner)
  return self._result(self.state,req,ResultStatus.APPLIED,"kill_switch_updated",new)
 def failover(self,transition_id,expected,scope):
  req=TransitionRequest(transition_id,expected,self.state.phase,self.state.phase,self.state.owner,scope,"failover")
  if expected!=self.state.generation:return self._result(self.state,req,ResultStatus.CONFLICT,"generation_conflict")
  return self._result(self.state,req,ResultStatus.FAILOVER_NOT_ALLOWED,"failover_unverified")
