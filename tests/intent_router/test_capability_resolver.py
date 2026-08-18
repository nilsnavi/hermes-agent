"""Sprint 1.3.0 §33 — Capability Resolver tests.

Deterministic intent/subtype → capability requirement mapping. No LLM,
no network, no DB — the resolver is a pure lookup (§7).
"""

from agent.capability_router.capabilities import (
    AccessMode,
    ApprovalPolicy,
    Capability,
    NetworkPolicy,
)
from agent.capability_router.resolver import CapabilityResolver


def _r():
    return CapabilityResolver()


# ── §33 STATUS_READ subtype → capability ───────────────────────────


def test_gateway_status_resolves_status_gateway():
    got = _r().resolve("status_read", "gateway_status")
    assert got is not None
    assert got.requirement.capability is Capability.STATUS_GATEWAY
    assert got.tool == "gateway_status"


def test_runtime_status_resolves_status_runtime():
    got = _r().resolve("status_read", "runtime_status")
    assert got is not None
    assert got.requirement.capability is Capability.STATUS_RUNTIME
    assert got.tool == "runtime_status"


def test_integration_status_resolves_status_integration():
    got = _r().resolve("status_read", "integration_status")
    assert got is not None
    assert got.requirement.capability is Capability.STATUS_INTEGRATION
    assert got.tool == "integration_status"


def test_scheduler_status_resolves_status_scheduler():
    got = _r().resolve("status_read", "scheduler_status")
    assert got is not None
    assert got.requirement.capability is Capability.STATUS_SCHEDULER
    assert got.tool == "scheduler_status"


def test_provider_status_resolves_status_provider():
    got = _r().resolve("status_read", "provider_status")
    assert got is not None
    assert got.requirement.capability is Capability.STATUS_PROVIDER
    assert got.tool == "provider_status"


def test_health_service_generic_map_to_runtime():
    """HEALTH/SERVICE/GENERIC subtypes sit under STATUS_RUNTIME while
    the per-request tool honors the verified 1.2.1 subtype contract."""
    health = _r().resolve("status_read", "health_status")
    assert health is not None
    assert health.requirement.capability is Capability.STATUS_RUNTIME
    assert health.tool == "health_status"  # legacy subtype tool preserved
    service = _r().resolve("status_read", "service_status")
    assert service is not None
    assert service.tool == "runtime_status"
    generic = _r().resolve("status_read", "generic")
    assert generic is not None
    assert generic.tool == "runtime_status"


def test_search_read_resolves_operational_search():
    got = _r().resolve("search_read", "log_search")
    assert got is not None
    assert got.requirement.capability is Capability.OPERATIONAL_SEARCH
    assert got.tool == "operational_log_search"
    # every verified search subtype resolves to the same tool
    for st in ("event_search", "scheduler_search", "provider_search",
               "integration_search"):
        assert _r().resolve("search_read", st).tool == \
            "operational_log_search"


def test_requirement_is_read_only_contract():
    """§3 — every current requirement is READ_ONLY/NONE/idempotent/
    local/no-approval/max_tools=1."""
    got = _r().resolve("status_read", "gateway_status")
    req = got.requirement
    assert req.access_mode is AccessMode.READ_ONLY
    assert req.side_effect == "NONE"
    assert req.idempotency_required is True
    assert req.network_policy is NetworkPolicy.LOCAL_ONLY
    assert req.approval_policy is ApprovalPolicy.NONE
    assert req.max_tool_calls == 1


# ── §33 NO_CAPABILITY ──────────────────────────────────────────────


def test_unknown_has_no_capability():
    assert _r().resolve("unknown") is None
    assert _r().resolve("unknown", "generic") is None


def test_write_has_no_read_capability():
    """Unsafe families NEVER resolve to a read capability (§11 no
    production expansion — an unsafe intent must not be satisfiable
    by the verified read-only surface)."""
    for intent in ("write_action", "delete_action", "system_action",
                   "schedule_action", "approval_action"):
        assert _r().resolve(intent) is None


def test_off_scope_read_intents_have_no_capability():
    """INFORMATION_READ/DIAGNOSTIC/ANALYSIS are NOT enforced in 1.2.4
    and must not gain V2 authority through the capability router."""
    for intent in ("information_read", "diagnostic", "analysis",
                   "summarization", "code_assist", "planning",
                   "conversation"):
        assert _r().resolve(intent) is None


def test_resolver_is_deterministic():
    """Same input → same output object identity (cached), never varies."""
    r = _r()
    a = r.resolve("status_read", "provider_status")
    b = r.resolve("status_read", "provider_status")
    assert a is b
    assert a.tool == b.tool
    assert a.requirement.capability is b.requirement.capability
