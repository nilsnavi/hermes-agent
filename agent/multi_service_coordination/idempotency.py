"""Sprint 1.3.15 — global idempotency and exactly-once coordination.

Semantic key = baseline + service_set(+version) + operation_set + config
fingerprints + registry digest + graph digest.  Time-invariant by design (a
field that changes per run, like a timestamp, would defeat exactly-once).

A duplicate global intent returns the prior simulated result with ZERO new
approvals, budgets, simulations or adapter calls.
"""
from __future__ import annotations

import hashlib

from .models import MultiServiceChangePlan


def semantic_key(plan: MultiServiceChangePlan, registry_digest: str) -> str:
    payload = "\u001f".join(
        [
            plan.baseline_sha,
            ",".join(f"{sp.service_id}:{sp.service_profile_version}" for sp in plan.service_set),
            ",".join(plan.operation_set),
            ",".join(sp.config_fingerprint for sp in plan.service_set),
            registry_digest,
            plan.dependency_graph_digest,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["semantic_key"]