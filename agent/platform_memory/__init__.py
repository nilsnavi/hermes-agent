"""Memory Intelligence Platform — memory control plane.

Memory in this platform is DATA, never AUTHORITY. Nothing here can grant a
capability, approve execution, mutate policy, or bypass SystemBoundary. New
memory integrates only through the MemoryProvider seam.
"""

from __future__ import annotations

from .exceptions import (
    MemoryError,
    MemoryInjectionDetected,
    MemoryNotFound,
    MemoryPermissionDenied,
    MemoryProvenanceError,
    MemoryScopeError,
    MemoryStateError,
)
from .memory_gateway import UnifiedMemoryGateway
from .memory_lifecycle import (
    InvalidMemoryTransition,
    MemoryLifecycle,
    MemoryLifecycleStatus,
    MemoryLifecycleTransition,
)
from .memory_provider import MemoryProvider, MemoryProviderCoordinator
from .memory_scopes import MemoryAccess, MemoryKey, MemoryScope, require_accessible
from .memory_security import redact_secrets, sanitize_payload
from .memory_workflows import (
    ConsolidateWorkflow,
    ForgetWorkflow,
    MemoryWorkflowError,
    RememberWorkflow,
)
from .provenance import ProvenanceRecord, ProvenanceSource
from .retrieval import CandidateSource, ContextItem, RetrievalPipeline
from .storage_backends import (
    AuthorityWorkStore,
    LongTermStore,
    MemoryQuery,
    NoStorageBackend,
    SemanticIndex,
    ShortTermStore,
    StoredMemory,
)

__all__ = [
    "AuthorityWorkStore",
    "CandidateSource",
    "ConsolidateWorkflow",
    "ContextItem",
    "ForgetWorkflow",
    "InvalidMemoryTransition",
    "LongTermStore",
    "MemoryAccess",
    "MemoryError",
    "MemoryInjectionDetected",
    "MemoryKey",
    "MemoryLifecycle",
    "MemoryLifecycleStatus",
    "MemoryLifecycleTransition",
    "MemoryNotFound",
    "MemoryPermissionDenied",
    "MemoryProvenanceError",
    "MemoryProvider",
    "MemoryProviderCoordinator",
    "MemoryQuery",
    "MemoryScope",
    "MemoryScopeError",
    "MemoryStateError",
    "MemoryWorkflowError",
    "NoStorageBackend",
    "ProvenanceRecord",
    "ProvenanceSource",
    "RememberWorkflow",
    "RetrievalPipeline",
    "SemanticIndex",
    "ShortTermStore",
    "StoredMemory",
    "UnifiedMemoryGateway",
    "redact_secrets",
    "require_accessible",
    "sanitize_payload",
]