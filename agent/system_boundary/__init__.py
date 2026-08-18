"""System Boundary Layer (Sprint 1.3.3).

Fail-closed boundary between policy decisions and real tool execution.
Replaces NoopSystemBoundary in the VerifiedToolExecutor pipeline:

    preflight → authorize → verify_before_execute → adapter
               → verify_after_execute

Restrictive boundary, NOT a permission source: it can classify,
compute effective actions, detect indirect execution, determine blast
radius, raise risk, require approval/validation/fresh preflight and
BLOCK — it can never reduce risk, grant capability authority,
approve, create permissions, bypass PolicyDecision or perform
remediation/rollback.
"""

from .boundary import SBL_VERSION, SystemBoundaryLayer
from .models import (
    BoundaryDecision,
    EffectiveActionClass,
    GraphHealth,
    OperationClass,
    Provenance,
    ResourceClass,
    SystemPreflightPlan,
    block_decision,
    pass_decision,
    revalidate_decision,
)
from .exceptions import (
    SBLBaseError,
    SBLBlocked,
    SBLBypassDetected,
    SBLGraphUnavailable,
    SBLInternalError,
    SBLPathUnresolved,
    SBLRevalidateRequired,
)

__version__ = SBL_VERSION

__all__ = [
    "SBL_VERSION",
    "SystemBoundaryLayer",
    "BoundaryDecision",
    "SystemPreflightPlan",
    "ResourceClass",
    "OperationClass",
    "EffectiveActionClass",
    "GraphHealth",
    "Provenance",
    "block_decision",
    "pass_decision",
    "revalidate_decision",
    "SBLBaseError",
    "SBLInternalError",
    "SBLBlocked",
    "SBLRevalidateRequired",
    "SBLBypassDetected",
    "SBLPathUnresolved",
    "SBLGraphUnavailable",
]
