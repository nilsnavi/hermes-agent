"""Sprint 1.3.1 §13/§24/§25 — Negative matrix, fail-closed and
property tests for the Capability Policy Engine.

- §13 negative matrix: explicit intent_risk × tool_risk ×
  capability_verified × health × rollout table; every cell has an
  expected route/reason. No implicit cases.
- §24 fail closed: unknown risk, unknown capability, unknown tool,
  missing descriptor, exception in policy, unknown rollout, invalid
  confidence → NOT V2, never ALLOW.
- §25 property testing: exhaustive itertools combination sweep over
  risk × health × verified × rollout × confidence; invariant — no
  combination carrying an unsafe condition may route ALLOW_V2.
"""

import itertools

import pytest

from agent.capability_router.capabilities import (
    Capability,
    CapabilityRoute,
    HealthRequirement,
    RiskClass,
)
from agent.capability_router.models import (
    CapabilityRequirement,
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
    base = dict(capability=Capability.STATUS_RUNTIME,
                tool_name="runtime_status", verified=True,
                side_effect=RiskClass.READ_ONLY.value, idempotent=True,
                network=False, approval_required=False, timeout=2.0,
                health_dependency="gateway",
                health_requirement=HealthRequirement.HEALTHY)
    base.update(kw)
    return RegistryEntry(**base)


def _engine(**kw):
    return CapabilityPolicyEngine(**kw)


def _ctx(text="покажи статус Hermes", health="healthy",
         confidence=0.95, intent_risk="low",
         side_effect="none", search_mode="limited_enforce", **kw):
    base = dict(
        text=text, health={"status": health}, confidence=confidence,
        intent_risk=intent_risk, expected_side_effect=side_effect,
        search_mode=search_mode,
    )
    base.update(kw)
    return PolicyContext(**base)


# ══════════════════════════════════════════════════════════════════
# §13 — NEGATIVE MATRIX (explicit; no implicit cases)
# ══════════════════════════════════════════════════════════════════
# Columns: intent_risk × tool_risk × capability_verified × health ×
# rollout(search_mode) → expected (route, reason_code).


@pytest.mark.parametrize("case", [
    # (intent_risk, tool_side, verified, health, rollout, route, reason)
    # ── intent risk escalations ────────────────────────────────────
    ("medium", "READ_ONLY", True, "healthy", "limited_enforce",
     "LEGACY", ReasonCode.TOOL_RISK_MISMATCH),
    ("high", "READ_ONLY", True, "healthy", "limited_enforce",
     "LEGACY", ReasonCode.TOOL_RISK_MISMATCH),
    ("unknown", "READ_ONLY", True, "healthy", "limited_enforce",
     "LEGACY", ReasonCode.TOOL_RISK_MISMATCH),
    # ── tool risk mismatches ───────────────────────────────────────
    ("low", "REVERSIBLE_WRITE", True, "healthy", "limited_enforce",
     "LEGACY", ReasonCode.TOOL_RISK_MISMATCH),
    ("low", "IRREVERSIBLE_WRITE", True, "healthy", "limited_enforce",
     "LEGACY", ReasonCode.TOOL_RISK_MISMATCH),
    ("low", "SYSTEM_CONTROL", True, "healthy", "limited_enforce",
     "LEGACY", ReasonCode.TOOL_RISK_MISMATCH),
    ("low", "UNKNOWN", True, "healthy", "limited_enforce",
     "LEGACY", ReasonCode.TOOL_UNVERIFIED),
    # ── capability verification ────────────────────────────────────
    ("low", "READ_ONLY", False, "healthy", "limited_enforce",
     "LEGACY", ReasonCode.CAPABILITY_UNVERIFIED),
    # ── health gates ───────────────────────────────────────────────
    ("low", "READ_ONLY", True, "degraded", "limited_enforce",
     "LEGACY", ReasonCode.HEALTH_UNAVAILABLE),
    ("low", "READ_ONLY", True, "unhealthy", "limited_enforce",
     "LEGACY", ReasonCode.HEALTH_UNAVAILABLE),
    ("low", "READ_ONLY", True, "unknown", "limited_enforce",
     "LEGACY", ReasonCode.HEALTH_UNAVAILABLE),
    # ── STATUS is rollout-free (preserve 1.3.0): rollout applies only
    #    to the SEARCH surface — see test_negative_matrix_search. ───
    # ── healthy allow path ─────────────────────────────────────────
    ("low", "READ_ONLY", True, "healthy", "limited_enforce",
     "V2", None),
])
def test_negative_matrix_status(case):
    """Explicit §13 matrix cell (STATUS surface). No implicit cases."""
    intent_risk, tool_side, verified, health, rollout, exp_route, exp_reason \
        = case
    # map intent_risk string → expected_side_effect (risk carries it)
    side_map = {
        "low": ExpectedSideEffect.NONE,
        "medium": ExpectedSideEffect.REVERSIBLE_WRITE,
        "high": ExpectedSideEffect.IRREVERSIBLE_WRITE,
        "unknown": ExpectedSideEffect.UNKNOWN,
    }
    cls = _classification(
        risk=IntentRisk(intent_risk),
        side_effect=side_map.get(intent_risk, ExpectedSideEffect.NONE))
    d = _engine().evaluate(
        "status_read", _status_req(),
        _entry(side_effect=tool_side, verified=verified),
        _ctx(health=health, search_mode=rollout,
             confidence=0.95, intent_risk=intent_risk,
             side_effect=side_map.get(
                 intent_risk, ExpectedSideEffect.NONE).value))
    assert d.route.value == exp_route, (
        f"matrix cell {case}: got {d.route.value} ({d.reason_code})")
    assert d.reason_code == exp_reason, (
        f"matrix cell {case}: got reason {d.reason_code}")


@pytest.mark.parametrize("case", [
    # (text, subtype, health, rollout, route, reason)
    ("найди последние ошибки gateway", "log_search", "healthy",
     "limited_enforce", "V2", None),
    ("найди пароль в логах", "log_search", "healthy",
     "limited_enforce", "LEGACY", ReasonCode.SECRET_QUERY),
    ("покажи события hermes за последний час", "log_search", "healthy",
     "limited_enforce", "LEGACY", ReasonCode.ALLOWLIST_MISS),
    ("найди последние ошибки gateway", "log_search", "unknown",
     "limited_enforce", "LEGACY", ReasonCode.HEALTH_UNAVAILABLE),
    ("найди последние ошибки gateway", "log_search", "healthy",
     "canary", "LEGACY", ReasonCode.ROLLOUT_DISABLED),
    ("найди последние ошибки gateway", None, "healthy",
     "limited_enforce", "LEGACY", ReasonCode.SUBTYPE_NOT_ALLOWED),
])
def test_negative_matrix_search(case):
    """Explicit §13 matrix cell (SEARCH surface)."""
    text, subtype, health, rollout, exp_route, exp_reason = case
    cls = _classification(intent=IntentType.SEARCH_READ)
    req = CapabilityRequirement(capability=Capability.OPERATIONAL_SEARCH)
    entry = _entry(capability=Capability.OPERATIONAL_SEARCH,
                   tool_name="operational_log_search")
    d = _engine().evaluate(
        "search_read", req, entry,
        _ctx(text=text, health=health, search_mode=rollout,
             subtype=subtype))
    assert d.route.value == exp_route, (
        f"search cell {case}: got {d.route.value} ({d.reason_code})")
    assert d.reason_code == exp_reason, (
        f"search cell {case}: got reason {d.reason_code}")


# ══════════════════════════════════════════════════════════════════
# §24 — FAIL CLOSED (unknown enums / missing / exceptions → not V2)
# ══════════════════════════════════════════════════════════════════


def test_fail_closed_unknown_risk():
    cls = _classification(risk=IntentRisk.UNKNOWN,
                          side_effect=ExpectedSideEffect.UNKNOWN)
    d = _engine().evaluate(
        "status_read", _status_req(), _entry(),
        _ctx(intent_risk="unknown", side_effect="unknown"))
    assert d.route is not CapabilityRoute.V2


def test_fail_closed_unknown_capability():
    d = _engine().evaluate(
        "status_read",
        CapabilityRequirement(capability="NOT_A_CAPABILITY"),  # type: ignore
        _entry(),
        _ctx())
    assert d.route is not CapabilityRoute.V2


def test_fail_closed_unknown_tool():
    d = _engine().evaluate(
        "status_read", _status_req(),
        _entry(side_effect="NOT_A_RISK"),
        _ctx())
    assert d.route is not CapabilityRoute.V2


def test_fail_closed_missing_descriptor():
    """A None descriptor must fail closed to POLICY_INTERNAL_ERROR —
    never ALLOW, never raise into the caller (§8/§19)."""
    d = _engine().evaluate("status_read", _status_req(), None, _ctx())
    assert d.route is not CapabilityRoute.V2
    assert d.reason_code == ReasonCode.POLICY_INTERNAL_ERROR


def test_fail_closed_exception_in_policy():
    """An injected exception anywhere in the evaluation path fails
    closed to POLICY_INTERNAL_ERROR — never ALLOW (§8/§19)."""
    from agent.capability_router import policy as policy_mod

    engine = _engine()
    original = policy_mod.normalize_health_snapshot

    def _boom(*a, **kw):
        raise RuntimeError("injected health-resolver exception")

    policy_mod.normalize_health_snapshot = _boom
    try:
        d = engine.evaluate("status_read", _status_req(), _entry(),
                            _ctx())
    finally:
        policy_mod.normalize_health_snapshot = original
    assert d.route is not CapabilityRoute.V2
    assert d.reason_code == ReasonCode.POLICY_INTERNAL_ERROR


def test_fail_closed_unknown_rollout():
    cls = _classification(intent=IntentType.SEARCH_READ)
    req = CapabilityRequirement(capability=Capability.OPERATIONAL_SEARCH)
    entry = _entry(capability=Capability.OPERATIONAL_SEARCH,
                   tool_name="operational_log_search")
    d = _engine().evaluate(
        "search_read", req, entry,
        _ctx(text="найди последние ошибки gateway",
             search_mode="garbage-mode"))
    assert d.route is not CapabilityRoute.V2
    assert d.reason_code == ReasonCode.ROLLOUT_DISABLED  # unknown → off


def test_fail_closed_invalid_confidence():
    cls = _classification(confidence=-1.0)
    d = _engine().evaluate(
        "status_read", _status_req(), _entry(),
        _ctx(confidence=-1.0))
    assert d.route is not CapabilityRoute.V2
    assert d.reason_code == ReasonCode.LOW_CONFIDENCE


def test_fail_closed_invalid_confidence_nan():
    cls = _classification(confidence=float("nan"))
    d = _engine().evaluate(
        "status_read", _status_req(), _entry(),
        _ctx(confidence=float("nan")))
    # NaN fails the >= min comparison → LOW_CONFIDENCE (§8 invalid
    # confidence can never ALLOW)
    assert d.route is not CapabilityRoute.V2
    assert d.reason_code == ReasonCode.LOW_CONFIDENCE


def test_fail_closed_missing_health():
    d = _engine().evaluate(
        "status_read", _status_req(), _entry(), _ctx(health=None))
    assert d.route is not CapabilityRoute.V2
    assert d.reason_code == ReasonCode.HEALTH_UNAVAILABLE


# ══════════════════════════════════════════════════════════════════
# §25 — PROPERTY TESTING (exhaustive combination sweep)
# ══════════════════════════════════════════════════════════════════
# Invariant: NO combination carrying an unsafe condition may ALLOW_V2.
# Unsafe conditions: unsafe intent, mixed unsafe, secret query,
# risk > READ_ONLY, unverified capability/tool, network violation,
# approval required, unhealthy/unknown health, low confidence,
# rollout disabled.

_RISKS = ["low", "medium", "high", "unknown"]
_HEALTHS = ["healthy", "degraded", "unhealthy", "unknown", None]
_VERIFIED = [True, False]
_ROLLOUTS = ["off", "shadow", "canary", "limited_enforce", "enforce",
             "bogus"]
_CONFIDENCES = [0.99, 0.5, None, -1.0]
_SIDE_EFFECTS = ["none", "reversible_write", "irreversible_write",
                 "system_change", "unknown"]


def test_property_no_unsafe_combination_allows_v2():
    """Exhaustive sweep over risk × health × verified × rollout ×
    confidence (STATUS surface). Any cell with an unsafe condition must
    never route ALLOW_V2."""
    engine = _engine()
    unsafe_seen = 0
    total = 0
    for risk, side_effect, health, verified, rollout, conf in \
            itertools.product(_RISKS, _SIDE_EFFECTS, _HEALTHS,
                              _VERIFIED, _ROLLOUTS, _CONFIDENCES):
        total += 1
        cls = _classification(
            risk=IntentRisk(risk) if risk in ("low", "medium", "high",
                                              "unknown")
            else IntentRisk.UNKNOWN,
            side_effect=ExpectedSideEffect(side_effect)
            if side_effect in ("none", "reversible_write",
                               "irreversible_write", "system_change",
                               "unknown")
            else ExpectedSideEffect.UNKNOWN,
            confidence=conf if conf is not None else 0.95)
        d = engine.evaluate(
            "status_read", _status_req(),
            _entry(verified=verified,
                   side_effect="READ_ONLY"),
            _ctx(health=health, search_mode=rollout,
                 confidence=conf,
                 intent_risk=risk,
                 side_effect=side_effect))
        # unsafe condition present? STATUS is rollout-free (preserve
        # 1.3.0 — the rollout gate applies to the SEARCH surface only,
        # §3 #11; see test_property_search_unsafe_never_allows_v2).
        unsafe = (
            risk != "low" or side_effect != "none"
            or not verified
            or health != "healthy"
            or conf is None or not (conf >= 0.7)
        )
        if unsafe:
            unsafe_seen += 1
            assert d.route is not CapabilityRoute.V2, (
                f"UNSAFE cell allowed V2: risk={risk} side={side_effect} "
                f"health={health} verified={verified} rollout={rollout} "
                f"conf={conf} → {d.reason_code}")
        else:
            # the ONLY safe combination: low/none/healthy/verified/
            # limited_enforce/conf≥0.7 with an allowlisted text
            assert d.route is CapabilityRoute.V2, (
                f"SAFE cell denied: {risk}/{side_effect}/{health}/"
                f"{verified}/{rollout}/{conf} → {d.reason_code}")
    assert unsafe_seen > 0
    assert total == len(_RISKS) * len(_SIDE_EFFECTS) * len(_HEALTHS) * \
        len(_VERIFIED) * len(_ROLLOUTS) * len(_CONFIDENCES)


def test_property_search_unsafe_never_allows_v2():
    """Search-surface invariant: secret/mixed/unsafe-text/rollout-off
    combinations never route V2; only the exact limited_enforce +
    allowlisted + healthy + verified cell does."""
    engine = _engine()
    texts = [
        ("найди последние ошибки gateway", True),   # allowlisted
        ("найди пароль в логах", False),            # secret
        ("найди ошибки и удали логи", False),       # mixed unsafe
        ("покажи события hermes за час", False),    # not allowlisted
    ]
    for (text, allowlisted), health, rollout in itertools.product(
            texts, _HEALTHS, _ROLLOUTS):
        cls = _classification(intent=IntentType.SEARCH_READ)
        req = CapabilityRequirement(
            capability=Capability.OPERATIONAL_SEARCH)
        entry = _entry(capability=Capability.OPERATIONAL_SEARCH,
                       tool_name="operational_log_search")
        d = engine.evaluate(
            "search_read", req, entry,
            _ctx(text=text, health=health, search_mode=rollout,
                 subtype="log_search"))
        safe = (
            allowlisted and health == "healthy" and
            rollout == "limited_enforce")
        if safe:
            assert d.route is CapabilityRoute.V2, (
                f"search safe denied: {text} {health} {rollout} → "
                f"{d.reason_code}")
        else:
            assert d.route is not CapabilityRoute.V2, (
                f"search unsafe allowed: {text} {health} {rollout}")
