"""Provider-neutral capability and approval contracts."""
from dataclasses import dataclass
from enum import Enum
import hashlib, json
from typing import Mapping
import math

def _validate_json(value):
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value): raise ValueError("non-finite number is not supported")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str): raise TypeError("JSON object keys must be strings")
            _validate_json(item)
        return
    if isinstance(value, list):
        for item in value: _validate_json(item)
        return
    raise TypeError("value is outside the supported JSON argument domain")

def argument_binding(arguments: Mapping[str, object]) -> str:
    _validate_json(arguments)
    encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

class AuthorizationStatus(str, Enum):
    AUTHORIZED="authorized"; DENIED="denied"; APPROVAL_REQUIRED="approval_required"; EXPIRED="expired"; REVOKED="revoked"; CONTEXT_MISMATCH="context_mismatch"; ARGUMENT_MISMATCH="argument_mismatch"; INVALID_GRANT="invalid_grant"

@dataclass(frozen=True)
class CapabilityGrant:
    grant_id: str; principal_id: str; session_id: str; turn_id: str; tool_call_id: str; tool_name: str; argument_binding: str; approval_required: bool=False; issued_at: int=0; expires_at: int|None=None; revoked: bool=False; policy_version: str=""

@dataclass(frozen=True)
class Approval:
    session_id: str; turn_id: str; tool_call_id: str; tool_name: str; argument_binding: str

@dataclass(frozen=True)
class AuthorizationResult:
    status: AuthorizationStatus; reason_code: str
    @property
    def authorized(self) -> bool: return self.status is AuthorizationStatus.AUTHORIZED

def validate_grant(grant: CapabilityGrant|None, *, principal_id: str, session_id: str, turn_id: str, tool_call_id: str, tool_name: str, arguments: Mapping[str, object], evaluation_time: int, approval: Approval|None=None) -> AuthorizationResult:
    if grant is None: return AuthorizationResult(AuthorizationStatus.INVALID_GRANT, "missing_grant")
    if not all(isinstance(value, str) and value for value in (grant.grant_id, grant.principal_id, grant.session_id, grant.turn_id, grant.tool_call_id, grant.tool_name, grant.argument_binding)):
        return AuthorizationResult(AuthorizationStatus.INVALID_GRANT, "malformed_grant")
    if evaluation_time < grant.issued_at: return AuthorizationResult(AuthorizationStatus.INVALID_GRANT, "grant_not_yet_valid")
    if grant.revoked: return AuthorizationResult(AuthorizationStatus.REVOKED, "grant_revoked")
    if grant.expires_at is not None and evaluation_time >= grant.expires_at: return AuthorizationResult(AuthorizationStatus.EXPIRED, "grant_expired")
    if (grant.principal_id, grant.session_id, grant.turn_id, grant.tool_call_id, grant.tool_name) != (principal_id, session_id, turn_id, tool_call_id, tool_name): return AuthorizationResult(AuthorizationStatus.CONTEXT_MISMATCH, "execution_context_mismatch")
    if grant.argument_binding != argument_binding(arguments): return AuthorizationResult(AuthorizationStatus.ARGUMENT_MISMATCH, "argument_binding_mismatch")
    if grant.approval_required:
        if approval is None: return AuthorizationResult(AuthorizationStatus.APPROVAL_REQUIRED, "approval_required")
        if approval != Approval(session_id, turn_id, tool_call_id, tool_name, grant.argument_binding): return AuthorizationResult(AuthorizationStatus.CONTEXT_MISMATCH, "approval_context_mismatch")
    return AuthorizationResult(AuthorizationStatus.AUTHORIZED, "authorized")
