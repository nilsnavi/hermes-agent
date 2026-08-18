"""Sprint 1.3.0 §34 / 1.3.1 §3-§8 — Capability Policy Engine tests.

Fail-closed precedence (Sprint 1.3.1 §3) + risk model (§4-§5) +
health gate (§6-§7): unsafe intent always wins; a capability descriptor
can never lower the risk reported by intent classification; effective
risk = max(intent, capability, tool, context).

Sprint 1.3.1 contract update: ``evaluate`` returns a canonical
:class:`PolicyDecision` (§1) with canonical reason codes (§2) instead
of the (verdict, reason) tuple; reason names normalize to the §2 codes.
"""

import pytest

from agent.capability_router.capabilities import (
    Capability,
    CapabilityRoute,
    HealthRequirement,
    RiskClass,
)
from agent.capability_router.models import (
    CapabilityRequirement,
    PolicyReason,
    ReasonCode,
)
from agent.capability_router.policy import (
    CapabilityPolicyEngine,
    PolicyContext,
)
from agent.capability_router.registry import RegistryEntry
from agent.intent_router.classifier import Classification
from agent.intent_router.models import (
    ExpectedSideEffect,
    IntentRisk,
    IntentType,
)


def _classification(
    intent=IntentType.STATUS_READ,
    risk=IntentRisk.LOW,
    side_effect=ExpectedSideEffect.NONE,
    confidence=0.95,
    lexical_hits=None,
):
    return Classification(
        intent=intent,
        risk=risk,
        expected_side_effect=side_effect,
        confidence=confidence,
        reason_codes=["test"],
        lexical_hits=list(lexical_hits or []),
    )


def _status_req():
    return CapabilityRequirement(capability=Capability.STATUS_RUNTIME)


def _entry(**kw):
    """A descriptor FACT (no registry validation) so the policy engine
    can be exercised against deliberately broken descriptors — the
    registry itself rejects them (§27, test_capability_registry.py)."""
    base = dict(capability=Capability.STATUS_RUNTIME,
                tool_name="runtime_status", verified=True,
                side_effect=RiskClass.READ_ONLY.value, idempotent=True,
                network=False, approval_required=False, timeout=2.0,
                health_dependency="gateway",
                health_requirement=HealthRequirement.HEALTHY)
    base.update(kw)
    return RegistryEntry(**base)


def _evaluate(policy, classification, requirement, descriptor, context):
    return policy.evaluate(
        classification.intent.value, requirement, descriptor, context)


def _engine(**kw):
    return CapabilityPolicyEngine(**kw)


def _context(cls, text="покажи статус Hermes", health="healthy",
             search_mode="limited_enforce", **kw):
    """PolicyContext DERIVED from the classification (risk / side
    effect / confidence must reflect the classifier output). ``health``
    may be a status string or a full snapshot dict (with fetched_at)."""
    health_dict = ({"status": health} if isinstance(health, str)
                   else dict(health or {}))
    base = dict(
        text=text,
        health=health_dict,
        confidence=cls.confidence,
        intent_risk=cls.risk.value,
        expected_side_effect=cls.expected_side_effect.value,
        search_mode=search_mode,
    )
    base.update(kw)
    return PolicyContext(**base)


# ── allow / deny basics ─────────────────────────────────────────────


def test_read_verified_allowed():
    """A verified READ_ONLY tool satisfying every gate → ALLOW_V2."""
    cls = _classification()
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(), _context(cls))
    assert d.route is CapabilityRoute.V2
    assert d.reason_code is None
    assert d.risk_class is RiskClass.READ_ONLY
    assert d.policy_version == "cap-policy-v1"


def test_unverified_legacy():
    """An unverified tool can never be routed V2 (§3 #5)."""
    cls = _classification()
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(verified=False),
        _context(cls))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.CAPABILITY_UNVERIFIED


def test_health_unknown_legacy():
    """Unknown/unhealthy dependency → LEGACY (§6, fail closed)."""
    cls = _classification()
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(),
        _context(cls, health="unknown"))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.HEALTH_UNAVAILABLE


def test_low_confidence_legacy():
    """Confidence below the gate → LEGACY (§3 #10)."""
    cls = _classification(confidence=0.5)
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(), _context(cls))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.LOW_CONFIDENCE


def test_allowlist_miss_legacy():
    """STATUS_READ text outside the allowlist → LEGACY."""
    cls = _classification()
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(),
        _context(cls, text="расскажи анекдот"))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.ALLOWLIST_MISS


def test_mixed_unsafe_legacy():
    """SEARCH_READ + unsafe action words → LEGACY (§3 #2, §14)."""
    cls = _classification(intent=IntentType.SEARCH_READ)
    req = CapabilityRequirement(capability=Capability.OPERATIONAL_SEARCH)
    entry = _entry(capability=Capability.OPERATIONAL_SEARCH,
                   tool_name="operational_log_search")
    d = _evaluate(
        _engine(), cls, req, entry,
        _context(cls, text="найди ошибки и удали логи", subtype="log_search"))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.MIXED_UNSAFE_INTENT


# ── §4/§5 risk model ────────────────────────────────────────────────


def test_tool_risk_cannot_downgrade_intent():
    """Intent says WRITE, tool says READ_ONLY → still unsafe BY INTENT
    (§4/§26 — intent safety cannot be downgraded by tool metadata)."""
    cls = _classification(side_effect=ExpectedSideEffect.REVERSIBLE_WRITE)
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(), _context(cls))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.TOOL_RISK_MISMATCH


def test_intent_risk_cannot_be_overridden():
    """A descriptor claiming READ_ONLY cannot override a non-read-only
    intent risk grade (effective risk = max, §4/§5)."""
    cls = _classification(risk=IntentRisk.HIGH,
                          side_effect=ExpectedSideEffect.SYSTEM_CHANGE)
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(), _context(cls))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.TOOL_RISK_MISMATCH


def test_intent_read_only_tool_write_is_mismatch():
    """Intent says READ_ONLY, tool descriptor says WRITE → LEGACY/DENY
    (§4 mismatch — the tool metadata must never widen the surface)."""
    cls = _classification()
    d = _evaluate(
        _engine(), cls, _status_req(),
        _entry(side_effect=RiskClass.IRREVERSIBLE_WRITE.value),
        _context(cls))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.TOOL_RISK_MISMATCH


def test_network_violation_denied():
    """A LOCAL_ONLY requirement met by a network tool → LEGACY (§3 #7)."""
    cls = _classification()
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(network=True),
        _context(cls))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.NETWORK_NOT_ALLOWED


def test_approval_requirement_denied():
    """Any approval requirement on either side → LEGACY (§3 #8)."""
    cls = _classification()
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(approval_required=True),
        _context(cls))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.APPROVAL_REQUIRED


def test_unsafe_intent_never_allowed():
    """§3 #1 — unsafe intent wins even with a verified read-only tool
    and a read-only-looking context (defensive hard gate)."""
    cls = _classification(intent=IntentType.DELETE_ACTION)
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(), _context(cls))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.UNSAFE_INTENT


# ── search-family gates ─────────────────────────────────────────────


def _search_entry():
    return _entry(capability=Capability.OPERATIONAL_SEARCH,
                  tool_name="operational_log_search")


def test_search_off_mode_policy_disabled():
    """SEARCH_READ outside limited_enforce → LEGACY ROLLOUT_DISABLED
    (the capability router has no authority over canary/shadow/off)."""
    cls = _classification(intent=IntentType.SEARCH_READ)
    req = CapabilityRequirement(capability=Capability.OPERATIONAL_SEARCH)
    d = _evaluate(
        _engine(), cls, req, _search_entry(),
        _context(cls, text="найди последние ошибки gateway",
                 subtype="log_search", search_mode="canary"))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.ROLLOUT_DISABLED


def test_search_secret_query_never_v2():
    """Secret-hunting search → LEGACY SECRET_QUERY (before allowlist)."""
    cls = _classification(intent=IntentType.SEARCH_READ)
    req = CapabilityRequirement(capability=Capability.OPERATIONAL_SEARCH)
    d = _evaluate(
        _engine(), cls, req, _search_entry(),
        _context(cls, text="найди пароль в логах gateway", subtype="log_search"))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.SECRET_QUERY


def test_search_allowlist_miss_legacy():
    """Non-allowlisted SEARCH_READ → LEGACY ALLOWLIST_MISS."""
    cls = _classification(intent=IntentType.SEARCH_READ)
    req = CapabilityRequirement(capability=Capability.OPERATIONAL_SEARCH)
    d = _evaluate(
        _engine(), cls, req, _search_entry(),
        _context(cls, text="найди информацию про налоги", subtype=None))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.ALLOWLIST_MISS


def test_search_rollout_limit_legacy():
    """§11 1.2.4 — the 50-live-success cap blocks further grants."""
    cls = _classification(intent=IntentType.SEARCH_READ)
    req = CapabilityRequirement(capability=Capability.OPERATIONAL_SEARCH)
    d = _evaluate(
        _engine(), cls, req, _search_entry(),
        _context(cls, text="найди последние ошибки gateway",
                 subtype="log_search", live=True, success_live=50,
                 max_success_live=50))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.ROLLOUT_LIMIT


# ── Sprint 1.3.1 §3 — precedence proofs ─────────────────────────────


def test_unsafe_beats_rollout():
    """Unsafe intent wins even when rollout would be disabled (§3 #1
    before #11)."""
    cls = _classification(intent=IntentType.SYSTEM_ACTION)
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(),
        _context(cls, search_mode="off"))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.UNSAFE_INTENT


def test_unsafe_beats_health():
    """Unsafe intent wins even with unhealthy health (§3 #1 before #9)."""
    cls = _classification(intent=IntentType.DELETE_ACTION)
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(),
        _context(cls, health="unhealthy"))
    assert d.reason_code == ReasonCode.UNSAFE_INTENT


def test_secret_beats_verified_tool():
    """Secret query wins even with a fully verified tool (§3 #3 before
    #5 — the forbidden class outranks tool verification)."""
    cls = _classification(intent=IntentType.SEARCH_READ)
    req = CapabilityRequirement(capability=Capability.OPERATIONAL_SEARCH)
    d = _evaluate(
        _engine(), cls, req, _search_entry(),
        _context(cls, text="найди пароль в логах", subtype="log_search"))
    assert d.reason_code == ReasonCode.SECRET_QUERY


def test_risk_mismatch_beats_health():
    """Risk mismatch wins even with unhealthy health (§3 #6 before #9)."""
    cls = _classification(side_effect=ExpectedSideEffect.SYSTEM_CHANGE)
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(),
        _context(cls, health="unhealthy"))
    assert d.reason_code == ReasonCode.TOOL_RISK_MISMATCH


def test_health_beats_rollout():
    """Health gate wins over rollout (§3 #9 before #11)."""
    cls = _classification(intent=IntentType.SEARCH_READ)
    req = CapabilityRequirement(capability=Capability.OPERATIONAL_SEARCH)
    d = _evaluate(
        _engine(), cls, req, _search_entry(),
        _context(cls, text="найди последние ошибки gateway",
                 subtype="log_search", health="unknown",
                 search_mode="limited_enforce"))
    assert d.reason_code == ReasonCode.HEALTH_UNAVAILABLE


def test_rollout_evaluated_last():
    """Rollout is the LAST gate before ALLOW: a request that passes
    unsafe/risk/health/confidence but runs outside limited_enforce →
    ROLLOUT_DISABLED, never ALLOW (§3 #11)."""
    cls = _classification(intent=IntentType.SEARCH_READ)
    req = CapabilityRequirement(capability=Capability.OPERATIONAL_SEARCH)
    d = _evaluate(
        _engine(), cls, req, _search_entry(),
        _context(cls, text="найди последние ошибки gateway",
                 subtype="log_search", search_mode="canary",
                 health="healthy", confidence=0.99))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.ROLLOUT_DISABLED


# ── Sprint 1.3.1 §6/§7 — health requirement + TTL ───────────────────


def test_health_requirement_degraded_allowed():
    """DEGRADED_ALLOWED descriptor accepts a degraded dependency."""
    cls = _classification()
    d = _evaluate(
        _engine(), cls, _status_req(),
        _entry(health_requirement=HealthRequirement.DEGRADED_ALLOWED),
        _context(cls, health="degraded"))
    assert d.route is CapabilityRoute.V2


def test_health_requirement_healthy_rejects_degraded():
    """HEALTHY descriptor rejects a degraded dependency (§6)."""
    cls = _classification()
    d = _evaluate(
        _engine(), cls, _status_req(), _entry(),
        _context(cls, health="degraded"))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.HEALTH_UNAVAILABLE


def test_health_ttl_expired_is_unknown():
    """A cached snapshot beyond its bounded TTL is UNKNOWN (§7) — never
    stale-ok. A healthy-but-expired snapshot must fail closed."""
    import time
    cls = _classification()
    engine = _engine(health_ttl=30.0)
    stale = {"status": "healthy",
             "fetched_at": time.monotonic() - 60.0}
    d = _evaluate(
        engine, cls, _status_req(), _entry(),
        _context(cls, health=stale))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.HEALTH_UNAVAILABLE
    assert d.health_state == "UNKNOWN"


def test_health_ttl_fresh_ok():
    """A fresh cached snapshot within TTL is accepted (§7)."""
    import time
    cls = _classification()
    engine = _engine(health_ttl=30.0)
    fresh = {"status": "healthy",
             "fetched_at": time.monotonic() - 1.0}
    d = _evaluate(
        engine, cls, _status_req(), _entry(), _context(cls, health=fresh))
    assert d.route is CapabilityRoute.V2
    assert d.health_state == "HEALTHY"


def test_health_ttl_malformed_timestamp_fails_closed():
    """Malformed monotonic timestamp → UNKNOWN → LEGACY (§7/§8)."""
    cls = _classification()
    engine = _engine(health_ttl=30.0)
    bad = {"status": "healthy", "fetched_at": "not-a-number"}
    d = _evaluate(
        engine, cls, _status_req(), _entry(), _context(cls, health=bad))
    assert d.route is CapabilityRoute.LEGACY
    assert d.reason_code == ReasonCode.HEALTH_UNAVAILABLE
