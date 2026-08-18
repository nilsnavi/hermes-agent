"""Sandbox Runtime exceptions (Sprint 1.3.5)."""


class SandboxError(Exception):
    """Base class for all sandbox runtime errors."""


class SandboxModelError(SandboxError):
    """Invalid request/plan model (unknown fields, illegal values)."""


class SandboxPathEscape(SandboxError):
    """Target resolves outside the sandbox root (lexical/symlink/absolute)."""


class SandboxPreflightFailed(SandboxError):
    """Preflight gate failed — mutation must not proceed."""


class ApprovalError(SandboxError):
    """Base approval error."""


class ApprovalInvalid(ApprovalError):
    """Approval does not match plan/run/version."""


class ApprovalExpired(ApprovalError):
    """Approval TTL expired."""


class ApprovalReuse(ApprovalError):
    """Approval already used / double-issue."""


class BackupFailed(SandboxError):
    """Snapshot/backup failed — mutation must not proceed."""


class LockConflict(SandboxError):
    """Resource is locked by another transaction."""


class LockStaleRecovered(SandboxError):
    """Stale lock detected and recovered (new owner granted)."""


class LockStateAmbiguous(LockConflict):
    """Expired lock cannot be released from TTL/PID evidence alone."""


class ResourceChangedAfterPreflight(SandboxError):
    """TOCTOU — resource changed between preflight and execution."""


class VerifyFailed(SandboxError):
    """Independent verification does not confirm the mutation."""


class HealthFailed(SandboxError):
    """Health gate failed after execution."""


class RollbackFailed(SandboxError):
    """Rollback could not restore the resource."""


class DuplicateAction(SandboxError):
    """Duplicate in-flight action with the same idempotency key."""


class AdapterAfterBlock(SandboxError):
    """Adapter was invoked after a BLOCK/DENY — invariant violation."""


class SandboxServiceError(SandboxError):
    """Sandbox test-service control error."""


class GatewaySelfControlBlocked(SandboxError):
    """Gateway self-restart/control attempt blocked."""


class IndirectControlBlocked(SandboxError):
    """Indirect gateway/system control (script, bash -c) blocked."""


class UnknownOperation(SandboxError):
    """Unknown mutation operation — DENY."""


class UnknownResource(SandboxError):
    """Unknown resource type — DENY."""


class UnknownExecutionResult(SandboxError):
    """Adapter returned an unclassifiable result — NO RETRY, manual review."""


class BoundaryRequired(SandboxError):
    """NoopSystemBoundary detected — sandbox execution forbidden."""


class KillSwitchActive(SandboxError):
    """Sandbox mutation disabled by feature flags (kill switch)."""


class PlanChangedAfterApproval(SandboxModelError):
    """Request/plan changed after approval — DENY."""
