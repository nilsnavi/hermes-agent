"""Sandbox Runtime (Sprint 1.3.5) — Controlled Sandbox Mutation Activation.

Standalone Hermes 2.0 module: proves state-changing execution is safe
INSIDE a sandbox, with production mutation hard-disabled.

    REQUEST → CLASSIFY → CAPABILITY → POLICY → BOUNDARY → PLAN
    → PREFLIGHT → APPROVAL → SNAPSHOT → LOCK → EXECUTE → VERIFY
    → HEALTH → COMMIT   |   failure → FREEZE → ROLLBACK → VERIFY
    → HEALTH → SAFE STATE → AUDIT

Chain position (1.3.4 pipeline → sandbox runtime):

    Intent Router
      → Capability Router V2
      → Capability Policy Engine
      → VerifiedToolExecutor
      → System Boundary Layer
      → Transactional System Change Pipeline
      → [Sandbox Mutation Runtime — REAL MUTATION ONLY INSIDE SANDBOX]

Safety: production mutation is impossible by construction — the only
executable targets are resources under the sandbox root; every real
change requires approval, snapshot, lock, verification, health and
commit. Production SYSTEM_CONTROL stays OFF.

stdlib-only: no gateway / scheduler / provider imports.
"""

from .models import (
    ResourceType,
    RiskClass,
    SandboxMutationPlan,
    SandboxMutationRequest,
    SandboxOperation,
    TransactionState,
)
from .root import SandboxRoot, resolve_sandbox_path

__version__ = "1.3.6"

__all__ = [
    "SandboxRoot",
    "resolve_sandbox_path",
    "SandboxMutationRequest",
    "SandboxMutationPlan",
    "SandboxOperation",
    "ResourceType",
    "RiskClass",
    "TransactionState",
    "__version__",
]
