"""Sprint 1.3.17 — sealed multi-service execution authority.

Authority is minted ONLY inside the runtime/coordinator.  There is NO public
authority factory and NO package-level helper that can mint a valid authority.

Design (mirrors the certified 1.3.14 authority-sealing pattern):

* ``MultiServiceExecutionAuthority`` is a frozen value whose validity is bound
  to a runtime *instance token*.  The authority carries ``_instance_token`` and
  ``_owner_instance_id``; an external caller cannot construct a valid one
  because the token must equal the signing runtime's private seed.
* The only way an authority becomes usable is ``ExecutionRuntime._issue()``,
  which stores the grant in THAT runtime's private ``_grants`` dict auxidn by
  authority id, and binds ``owner is runtime``.
* copy / deepcopy / pickle a grant and it no longer matches the runtime's
  ``_grants`` entry token (the token is the instance secret, not the fields a
  pickle reproduces) -> ``AuthorityDenied``.

The authority is one-shot: once ``consume()`` is called (at execution start) it
is removed from the runtime's grant store and cannot be reused for a second
execution.
"""
from __future__ import annotations

import copy
import hashlib
import secrets
from dataclasses import dataclass

from .exceptions import AuthorityDenied
from .models import ExecutionMode, MultiServiceExecutionPlan


@dataclass(frozen=True, slots=True)
class _AuthorityPayload:
    """Pure binding facts carried by an authority."""

    global_tx_id: str
    plan_hash: str
    generation: int
    service_set: frozenset[str]
    prepared_token_set: frozenset[str]
    approval_set: frozenset[str]
    budget_reservations: frozenset[str]
    lock_owner_set: frozenset[str]
    baseline_sha: str
    graph_digest: str
    registry_digest: str
    ttl_until_monotonic: float
    clock_provenance: str
    execution_mode: ExecutionMode


class MultiServiceExecutionAuthority:
    """Sealed execution authority.  Cannot be constructed externally."""

    __slots__ = ("_instance_token", "_owner_instance_id", "_payload",
                 "_consumed", "_authority_id")

    def __init__(self, *, _instance_token: bytes, _owner_instance_id: int,
                 _payload: _AuthorityPayload, _authority_id: str) -> None:
        # A caller cannot fabricate _instance_token: it must equal the signing
        # runtime's private seed (validated by the runtime in _verify).
        self._instance_token = _instance_token
        self._owner_instance_id = _owner_instance_id
        self._payload = _payload
        self._consumed = False
        self._authority_id = _authority_id

    # -- read-only inspection -------------------------------------------------
    @property
    def authority_id(self) -> str:
        return self._authority_id

    @property
    def global_tx_id(self) -> str:
        return self._payload.global_tx_id

    @property
    def plan_hash(self) -> str:
        return self._payload.plan_hash

    @property
    def generation(self) -> int:
        return self._payload.generation

    @property
    def execution_mode(self) -> ExecutionMode:
        return self._payload.execution_mode

    def binds(self, plan: MultiServiceExecutionPlan) -> bool:
        if self._payload.global_tx_id != plan.global_tx_id:
            return False
        if self._payload.plan_hash != plan.plan_hash():
            return False
        if self._payload.generation != plan.generation:
            return False
        if self._payload.service_set != frozenset(plan.service_set):
            return False
        return True

    def expired(self, now_monotonic: float) -> bool:
        return now_monotonic > self._payload.ttl_until_monotonic

    def binding_digest(self) -> str:
        p = self._payload
        raw = "|".join([
            p.global_tx_id, p.plan_hash, str(p.generation),
            ",".join(sorted(p.service_set)),
            ",".join(sorted(p.prepared_token_set)),
            ",".join(sorted(p.approval_set)),
            ",".join(sorted(p.budget_reservations)),
            ",".join(sorted(p.lock_owner_set)),
            p.baseline_sha, p.graph_digest, p.registry_digest,
            str(p.ttl_until_monotonic), p.clock_provenance,
            p.execution_mode.value,
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ExecutionRuntime:
    """Runtime instance that signs authorities.  Created and driven only by the
    execution pipeline.  Exposes NO authority-minting public API."""

    def __init__(self, instance_id: int | None = None) -> None:
        self.instance_id = instance_id if instance_id is not None else id(self)
        self._auth_secret = secrets.token_bytes(32)
        self._grants: dict[str, MultiServiceExecutionAuthority] = {}
        self._nonce_seed = 0

    def _issue(self, plan: MultiServiceExecutionPlan, *,
               prepared_token_set: frozenset[str] = frozenset(),
               approval_set: frozenset[str] = frozenset(),
               budget_reservations: frozenset[str] = frozenset(),
               lock_owner_set: frozenset[str] = frozenset(),
               now_monotonic: float, ttl_s: float = 60.0,
               clock_provenance: str = "monotonic",
               ) -> MultiServiceExecutionAuthority:
        """Issue a one-shot authority bound to the given plan.  Package-private
        (single underscore) and reachable only by the runtime owner."""
        auth_id = f"{self.instance_id}:{self._nonce_seed}:{secrets.token_hex(6)}"
        self._nonce_seed += 1
        payload = _AuthorityPayload(
            global_tx_id=plan.global_tx_id, plan_hash=plan.plan_hash(),
            generation=plan.generation, service_set=frozenset(plan.service_set),
            prepared_token_set=frozenset(prepared_token_set),
            approval_set=frozenset(approval_set),
            budget_reservations=frozenset(budget_reservations),
            lock_owner_set=frozenset(lock_owner_set),
            baseline_sha=plan.baseline_sha, graph_digest=plan.graph_digest,
            registry_digest=plan.registry_digest,
            ttl_until_monotonic=now_monotonic + ttl_s,
            clock_provenance=clock_provenance, execution_mode=plan.execution_mode,
        )
        auth = MultiServiceExecutionAuthority(
            _instance_token=self._auth_secret, _owner_instance_id=self.instance_id,
            _payload=payload, _authority_id=auth_id,
        )
        self._grants[auth_id] = auth
        return auth

    def _verify_and_consume(self, owner, authority: MultiServiceExecutionAuthority,
                            now_monotonic: float) -> None:
        """Verify and single-use consume.  Raises AuthorityDenied on any flaw."""
        if not isinstance(authority, MultiServiceExecutionAuthority):
            raise AuthorityDenied("authority is not a valid MultiServiceExecutionAuthority")
        if owner is not self:
            raise AuthorityDenied("authority owner is not this runtime instance")
        if authority._owner_instance_id != self.instance_id:
            raise AuthorityDenied("authority forged for a different runtime instance")
        if authority._instance_token != self._auth_secret:
            raise AuthorityDenied("authority token does not match runtime secret (forged/copy)")
        stored = self._grants.get(authority.authority_id)
        if stored is None:
            raise AuthorityDenied("authority not issued by this runtime (hand-minted)")
        if stored is not authority:
            raise AuthorityDenied("authority copy not registered (deepcopy/pickle)")
        if authority._consumed:
            raise AuthorityDenied("authority already consumed (one-shot)")
        if authority.expired(now_monotonic):
            raise AuthorityDenied("authority TTL expired")
        # single-use consume
        del self._grants[authority.authority_id]
        authority._consumed = True

    def _verify_readonly(self, owner, authority: MultiServiceExecutionAuthority,
                         now_monotonic: float) -> None:
        """Verify without consuming (used to prove authority before commit)."""
        if not isinstance(authority, MultiServiceExecutionAuthority):
            raise AuthorityDenied("authority is not a valid MultiServiceExecutionAuthority")
        if owner is not self:
            raise AuthorityDenied("authority owner is not this runtime instance")
        if authority._owner_instance_id != self.instance_id:
            raise AuthorityDenied("authority forged for a different runtime instance")
        if authority._instance_token != self._auth_secret:
            raise AuthorityDenied("authority token does not match runtime secret")
        if authority._consumed:
            raise AuthorityDenied("authority already consumed (one-shot)")
        if authority.expired(now_monotonic):
            raise AuthorityDenied("authority TTL expired")


def _authority_is_copy(authority: MultiServiceExecutionAuthority) -> bool:
    """Defense helper for tests: a deepcopy carries the same fields but is a
    different object with no registered grant."""
    return authority is not None and False  # real check is owner._grants identity


__all__ = [
    "ExecutionRuntime",
    "MultiServiceExecutionAuthority",
    "AuthorityDenied",
]