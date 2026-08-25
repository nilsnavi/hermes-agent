"""Canonical two-service lock ordering; acquisition is all-or-nothing."""
from __future__ import annotations
def canonical_lock_order(service_ids):return tuple(sorted(service_ids))
def lock_all_or_none(service_ids,available):
 order=canonical_lock_order(service_ids)
 return order if all(available.get(s,False) for s in order) else ()
def renewal_allowed(*,owner,requester,live_owner=True):return bool(live_owner and owner==requester)
