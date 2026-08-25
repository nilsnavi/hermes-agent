"""Runtime-owned canary authority; no public mint or executor capability."""
from __future__ import annotations
import secrets
from .models import ProductionCanaryRequest
_SEAL = object()
class ProductionCanaryAuthority:
    __slots__ = ("request_key", "runtime_id", "nonce", "_seal")
    def __init__(self, request_key: str = "", runtime_id: str = "", nonce: str = "", *, _seal=None):
        if _seal is not _SEAL: raise TypeError("canary authority is runtime-owned")
        self.request_key=request_key; self.runtime_id=runtime_id; self.nonce=nonce; self._seal=_seal
    def __reduce__(self):raise TypeError("canary authority is not serializable")
class CanaryRuntime:
    authority_type = ProductionCanaryAuthority
    __slots__ = ("_id", "_issued", "_used")
    def __init__(self): self._id=secrets.token_hex(16); self._issued={}; self._used=set()
    def _issue(self, request: ProductionCanaryRequest) -> ProductionCanaryAuthority:
        a=ProductionCanaryAuthority(request.semantic_key(),self._id,secrets.token_hex(16),_seal=_SEAL);self._issued[id(a)]=a.nonce;return a
    def _consume(self, authority: ProductionCanaryAuthority, request: ProductionCanaryRequest) -> bool:
        ident=id(authority)
        if type(authority) is not ProductionCanaryAuthority or authority.runtime_id!=self._id or authority.request_key!=request.semantic_key(): return False
        if self._issued.get(ident)!=authority.nonce or ident in self._used: return False
        self._used.add(ident);return True
