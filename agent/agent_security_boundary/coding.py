"""CodingAgent read-only enforcement.

Declares exactly which capability tokens the CodingAgent may be *admitted* for in
this phase. Only control-plane / read-only semantics are allowed; every mutation
capability is hard-denied regardless of what an AgentDefinition might claim.

A declaration is never a grant: even if an AgentDefinition lists a forbidden
token, admission for that token must be DENIED. The DENY set here is fixed and
cannot be expanded by registration or by any registry/channel.
"""

from __future__ import annotations

from .status import Disposition, SideEffectClass

# The only CodingAgent capability tokens that may be admitted (read-only).
CODING_READ_ONLY_CAPABILITIES = frozenset(
    {
        "read_repository",
        "inspect_files",
        "analyze_code",
        "produce_patch_proposal",
    }
)

# Fixed hard-deny set: never admissible, even if an AgentDefinition declares them.
CODING_FORBIDDEN_CAPABILITIES = frozenset(
    {
        "write_files",
        "execute_code",
        "install_dependency",
        "git_commit",
        "git_push",
        "run_shell",
        "service_control",
    }
)

# Mutation side-effect classes never admissible in this phase.
_MUTATION_CLASSES = frozenset(
    {
        SideEffectClass.WRITE,
        SideEffectClass.EXECUTE,
        SideEffectClass.SERVICE_MUTATION,
        SideEffectClass.SYSTEM_CONTROL,
    }
)


def is_forbidden_capability(capability: str) -> bool:
    """True if the capability token is in the fixed hard-deny set."""
    if not isinstance(capability, str):
        return True
    return capability in CODING_FORBIDDEN_CAPABILITIES


def is_read_only_capability(capability: str) -> bool:
    return isinstance(capability, str) and capability in CODING_READ_ONLY_CAPABILITIES


def classify_side_effect(capability: str) -> SideEffectClass:
    """Deterministic side-effect class for a capability token (pure classifier)."""
    if capability in ("write_files", "install_dependency", "git_commit", "git_push"):
        return SideEffectClass.WRITE
    if capability in ("execute_code", "run_shell"):
        return SideEffectClass.EXECUTE
    if capability == "service_control":
        return SideEffectClass.SERVICE_MUTATION
    if capability in ("read_repository", "inspect_files", "analyze_code", "produce_patch_proposal"):
        return SideEffectClass.READ_ONLY
    return SideEffectClass.UNKNOWN


def deny_disposition_for(capability: str) -> Disposition:
    """Always DENIED for a forbidden mutation capability (fail-closed)."""
    return Disposition.DENIED if is_forbidden_capability(capability) else Disposition.ADMITTED


__all__ = [
    "CODING_FORBIDDEN_CAPABILITIES",
    "CODING_READ_ONLY_CAPABILITIES",
    "classify_side_effect",
    "deny_disposition_for",
    "is_forbidden_capability",
    "is_read_only_capability",
]