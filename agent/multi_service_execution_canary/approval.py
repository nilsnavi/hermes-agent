"""Pure full-contract approval binding for one simulated transaction."""
from __future__ import annotations
import hashlib,json
def approval_binding(request)->str:
 payload={"baseline":request.baseline_sha,"generation":request.generation,"services":tuple(sorted(request.service_ids)),"registry":request.registry_digest,"graph":request.graph_digest,"plan":request.plan_hash,"risk":request.risk,"blast":request.blast,"operations":(request.operation,)}
 return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def approval_valid(request,binding,*,now):return bool(request.approval_id) and binding==approval_binding(request) and now<=request.expires_monotonic
