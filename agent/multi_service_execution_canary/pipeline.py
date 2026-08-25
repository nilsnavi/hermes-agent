"""Production-evidence admission and simulation-only canary pipeline."""
from __future__ import annotations
import concurrent.futures
import dataclasses
import time
from collections.abc import Mapping
from .adapter import _sealed_adapter
from .authority import CanaryRuntime
from .flags import ENABLED,MODE,real_execution_permitted,simulation_permitted
from .models import BASELINE_SHA,CanaryDecision,CanaryResult,ChildExecutionIntent,OPERATION,ProductionCanaryRequest,SimulatedOutcome
from .registry import CanaryServiceRegistry
from .store import CanaryStore
from .telemetry import CanaryTelemetry

_DENIED_IDS={"gateway","scheduler","provider","database","db","network","auth","security","docker","container","ssh","unknown","unregistered"}

@dataclasses.dataclass(frozen=True,slots=True)
class AdmissionResult:
    decision: CanaryDecision
    reason: str=""
    @property
    def allowed(self):return self.decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED

class MultiServiceCanaryAdmission:
    def __init__(self,registry=None):self.registry=registry or CanaryServiceRegistry()
    def evaluate(self,request: ProductionCanaryRequest,*,now:float,identity_valid:bool,graph_healthy:bool,approval_valid:bool,budget_available:bool,locks_available:bool,kill_switch_off:bool,system_control_off:bool,generic_service_control_denied:bool,real_adapter_disabled:bool)->AdmissionResult:
        ids=tuple(sorted(request.service_ids))
        if any(x.lower() in _DENIED_IDS for x in ids) or ids!=self.registry.service_ids():return AdmissionResult(CanaryDecision.DENIED,"service-set")
        if request.baseline_sha!=BASELINE_SHA:return AdmissionResult(CanaryDecision.REVALIDATE_REQUIRED,"baseline-drift")
        if request.registry_digest!=self.registry.digest:return AdmissionResult(CanaryDecision.REVALIDATE_REQUIRED,"registry-drift")
        if request.graph_digest!=self.registry.graph_digest or not graph_healthy:return AdmissionResult(CanaryDecision.REVALIDATE_REQUIRED,"graph-drift")
        if request.expires_monotonic<now:return AdmissionResult(CanaryDecision.REVALIDATE_REQUIRED,"expired")
        if request.operation!=OPERATION or request.risk!="MEDIUM_MUTATION_MODEL" or request.blast!="MULTI_SERVICE":return AdmissionResult(CanaryDecision.DENIED,"capability-binding")
        if request.approval_binding!=request.expected_approval_binding():return AdmissionResult(CanaryDecision.DENIED,"approval-binding")
        if not identity_valid:return AdmissionResult(CanaryDecision.DENIED,"identity")
        if not kill_switch_off:return AdmissionResult(CanaryDecision.CANARY_DISABLED,"kill-switch")
        if not all((approval_valid,budget_available,locks_available,system_control_off,generic_service_control_denied,real_adapter_disabled)):return AdmissionResult(CanaryDecision.DENIED,"gate")
        if real_execution_permitted({}):return AdmissionResult(CanaryDecision.DENIED,"real-execution")
        return AdmissionResult(CanaryDecision.GLOBAL_COMMITTED_SIMULATED,"admitted-for-simulation")

class CanaryPipeline:
    def __init__(self,root,*,clock=time.monotonic,env=None):
        self.registry=CanaryServiceRegistry();self.runtime=CanaryRuntime();self.admission=MultiServiceCanaryAdmission(self.registry)
        self.store=CanaryStore(root);self.telemetry=CanaryTelemetry();self._adapter=_sealed_adapter();self.clock=clock
        self.env={ENABLED:"true",MODE:"canary"} if env is None else env
    def real_execute(self,request,**gates):
        self.telemetry.authority_denials+=1;return CanaryDecision.DENIED
    def evaluate(self,request:ProductionCanaryRequest,*,identity_valid=True,graph_healthy=True,approval_valid=True,budget_available=True,locks_available=True,kill_switch_off=True,system_control_off=True,generic_service_control_denied=True,real_adapter_disabled=True,verify_ok=True,health_ok=True,stabilization_ok=True,scenario:Mapping[str,str]|None=None):
        self.telemetry.canary_requests+=1;key=request.semantic_key();claim,prior=self.store.claim(key)
        if claim=="TERMINAL":
            self.telemetry.canary_duplicates+=1
            return CanaryResult(CanaryDecision(prior["decision"]),0,True,False,"terminal-replay",tuple(tuple(x) for x in prior.get("child_outcomes",[])),tuple(prior.get("compensation_order",[])))
        if claim=="OWNED":
            prior=self.store.wait_terminal(key)
            if prior is not None:
                self.telemetry.canary_duplicates+=1
                return CanaryResult(CanaryDecision(prior["decision"]),0,True,False,"terminal-replay",tuple(tuple(x) for x in prior.get("child_outcomes",[])),tuple(prior.get("compensation_order",[])))
            self.telemetry.canary_denied+=1;return CanaryResult(CanaryDecision.DENIED,0,False,False,"claimed-by-other-timeout")
        effective_kill_off=kill_switch_off and not self.store.kill_switch()
        if not simulation_permitted(self.env):
            self.store.fail_before_simulation(key);self.telemetry.canary_denied+=1;return CanaryResult(CanaryDecision.CANARY_DISABLED,reason="flags-off")
        if not self.store.reserve_simulation_slot(key):
            self.store.fail_before_simulation(key);self.telemetry.canary_denied+=1;self.telemetry.kill_switch_denials+=1
            return CanaryResult(CanaryDecision.CANARY_DISABLED,reason="kill-switch-or-active-slot")
        admission=self.admission.evaluate(request,now=self.clock(),identity_valid=identity_valid,graph_healthy=graph_healthy,approval_valid=approval_valid,budget_available=budget_available,locks_available=locks_available,kill_switch_off=effective_kill_off,system_control_off=system_control_off,generic_service_control_denied=generic_service_control_denied,real_adapter_disabled=real_adapter_disabled)
        if admission.decision is not CanaryDecision.GLOBAL_COMMITTED_SIMULATED:
            self.store.fail_before_simulation(key);self.telemetry.canary_denied+=1
            if admission.decision is CanaryDecision.CANARY_DISABLED:self.telemetry.kill_switch_denials+=1
            return CanaryResult(admission.decision,reason=admission.reason)
        attempts,successes=self.store.budget()
        if attempts>=10 or successes>=5:
            self.store.fail_before_simulation(key);self.telemetry.canary_denied+=1;return CanaryResult(CanaryDecision.DENIED,reason="canary-budget")
        authority=self.runtime._issue(request);out=[];calls0=self._adapter.calls
        for sid in self.registry.execution_order():
            intent=ChildExecutionIntent(sid,OPERATION,request.plan_hash)
            outcome=self._adapter._simulate(intent,(scenario or {}).get(sid,"SIMULATED_SUCCESS"));out.append((sid,outcome.value));self.telemetry.simulated_child_calls+=1
            if outcome is not SimulatedOutcome.SIMULATED_SUCCESS:break
        calls=self._adapter.calls-calls0
        decision=CanaryDecision.GLOBAL_COMMITTED_SIMULATED;reason="committed-simulated";comp=()
        if any(v==SimulatedOutcome.SIMULATED_UNKNOWN.value for _,v in out):
            decision=CanaryDecision.UNKNOWN_OUTCOME;reason="unknown-no-retry";self.telemetry.canary_unknown+=1;self.telemetry.canary_recovery_required+=1
        elif any(v==SimulatedOutcome.SIMULATED_FAILURE.value for _,v in out):
            decision=CanaryDecision.COMPENSATION_REQUIRED_SIMULATED;reason="child-failed";comp=self.registry.compensation_order();self.telemetry.simulated_compensation_calls+=sum(v==SimulatedOutcome.SIMULATED_SUCCESS.value for _,v in out)
        elif not verify_ok or not health_ok or not stabilization_ok:
            decision=CanaryDecision.COMPENSATION_REQUIRED_SIMULATED;reason="post-adapter-gate";comp=self.registry.compensation_order();self.telemetry.simulated_compensation_calls+=len(out)
        elif not self.runtime._consume(authority,request):
            decision=CanaryDecision.DENIED;reason="authority-consume"
        receipt={"decision":decision.value,"child_outcomes":out,"compensation_order":comp,"real_effect_count":0,"real_global_commit":False,"reason":reason}
        self.store.terminal(key,receipt,success=decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED,approval_id=request.approval_id)
        self.telemetry.canary_simulated+=1;self.telemetry.canary_allowed+=int(decision is CanaryDecision.GLOBAL_COMMITTED_SIMULATED);self.telemetry.canary_denied+=int(decision is not CanaryDecision.GLOBAL_COMMITTED_SIMULATED)
        return CanaryResult(decision,calls,False,False,reason,tuple(out),tuple(comp))
    def record_crash_evidence(self,request,crash_point):
        from .recovery import CRASH_POINTS
        if crash_point not in CRASH_POINTS:raise ValueError("unknown crash point")
        sequences={
            "after-lock":("LOCKS_ACQUIRED",),"after-approval":("LOCKS_ACQUIRED","APPROVAL_CONSUMED"),
            "after-budget-reserve":("LOCKS_ACQUIRED","APPROVAL_CONSUMED","BUDGET_RESERVED"),
            "after-child-a":("LOCKS_ACQUIRED","CHILD_EFFECT_SIMULATED"),
            "before-child-b":("LOCKS_ACQUIRED","CHILD_EFFECT_SIMULATED"),
            "after-child-b":("LOCKS_ACQUIRED","CHILD_EFFECT_SIMULATED","CHILD_EFFECT_SIMULATED"),
            "before-verify":("LOCKS_ACQUIRED","CHILD_EFFECT_SIMULATED"),
            "after-verify":("LOCKS_ACQUIRED","CHILD_EFFECT_SIMULATED","VERIFY_SIMULATED_SUCCESS"),
            "before-simulated-global-commit":("LOCKS_ACQUIRED","CHILD_EFFECT_SIMULATED","VERIFY_SIMULATED_SUCCESS","STABILIZATION_SIMULATED_SUCCESS"),
            "after-simulated-global-commit":("LOCKS_ACQUIRED","CHILD_EFFECT_SIMULATED","VERIFY_SIMULATED_SUCCESS","STABILIZATION_SIMULATED_SUCCESS","GLOBAL_COMMITTED_SIMULATED")}
        for event in sequences[crash_point]:self.store.append_event(request.semantic_key(),event)
        return self.recover(request)
    def recover(self,request):
        from .recovery import CanaryRecoveryClassifier
        return CanaryRecoveryClassifier().classify(self.store.events(request.semantic_key()))
    def race(self,request,*,contenders=100,**gates):
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(32,contenders)) as pool:return list(pool.map(lambda _:self.evaluate(request,**gates),range(contenders)))

def build_canary_pipeline(root,*,clock=time.monotonic,env=None):return CanaryPipeline(root,clock=clock,env=env)
