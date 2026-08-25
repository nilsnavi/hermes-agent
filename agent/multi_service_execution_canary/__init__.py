"""Sprint 1.3.18 controlled multi-service execution canary foundation.

Production admission uses exact real context/evidence; child execution and global
commit remain simulation-only. REAL EXECUTION DISABLED. SYSTEM_CONTROL OFF.
"""
from .authority import CanaryRuntime,ProductionCanaryAuthority
from .flags import ALLOWED_MODES,ENABLED,MODE,REAL_CHILD_EXECUTION_ENABLED,enabled,mode,real_execution_permitted,simulation_permitted
from .models import BASELINE_SHA,CAPABILITY,OPERATION,CanaryDecision,CanaryResult,CanaryServiceProfile,CanaryServiceSet,ChildExecutionIntent,ProductionCanaryRequest,SimulatedOutcome
from .pipeline import CanaryPipeline,MultiServiceCanaryAdmission,build_canary_pipeline
from .registry import CanaryServiceRegistry
from .approval import approval_binding,approval_valid
from .barrier import CanaryExecutionBarrier,CanaryBarrierResult
from .budget import CanaryBudgetLimits,CanarySimulationBudget
from .commit import GLOBAL_COMMITTED_SIMULATED,global_commit_decision
from .composition import CERTIFIED_COMPONENTS,CertifiedComponentBindings
from .idempotency import semantic_canary_key
from .lock import canonical_lock_order,lock_all_or_none,renewal_allowed
from .preflight import PreflightEvidence
from .recovery import CRASH_POINTS,CanaryRecoveryClassifier,CanaryRecoveryPlan,compensation_steps
from .service_set import build_service_set
from .telemetry import CanaryTelemetry
from .verify import SimulatedVerification,verify_simulated
from .stabilization import stabilization_simulated_success
__version__="1.3.18"
__all__=["ALLOWED_MODES","BASELINE_SHA","CAPABILITY","CanaryDecision","CanaryPipeline","CanaryResult","CanaryRuntime","CanaryServiceProfile","CanaryServiceRegistry","CanaryServiceSet","CanaryTelemetry","ChildExecutionIntent","ENABLED","MODE","MultiServiceCanaryAdmission","OPERATION","ProductionCanaryAuthority","ProductionCanaryRequest","REAL_CHILD_EXECUTION_ENABLED","SimulatedOutcome","build_canary_pipeline","build_service_set","enabled","mode","real_execution_permitted","simulation_permitted"]
