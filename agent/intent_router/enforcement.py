"""Intent Router ENFORCEMENT — Sprint 1.2.0 (STATUS_READ only).

Controlled Intent Routing Enforcement: for the FIRST time the router
may influence REAL production routing — but ONLY for the strictly
limited, verified-safe class ``STATUS_READ`` (§1-6).

```
  request text
      |
      v
  EnforcementPolicy.evaluate(classification, features, health)
      |
      +-- allowed=True  -> V2_CANARY  (verified READ_ONLY tools only)
      +-- allowed=False -> LEGACY     (block_reason set, fail closed)
```

Enforcement is ALLOWED only when EVERY gate passes:

- intent == STATUS_READ (allowed_intents = {STATUS_READ})
- risk is read-only grade (LOW)
- expected_side_effect in (NONE, READ_ONLY)
- confidence >= min_confidence
- required capabilities fully verified (READ_RUNTIME_STATUS)
- provider/runtime health == HEALTHY
- request text passes the STATUS_READ allowlist (minimal, explicit)
- no approval required, no ambiguity

ANY failure of any gate → LEGACY (fallback_route, §6 FAIL CLOSED).
The router itself NEVER executes, switches, sends or calls tools —
the gateway honors the outcome and runs the read-only V2 canary path
(agent.gateway_v2.adapter.enforce_event) with the SafeCanaryToolRegistry
(write tools IMPOSSIBLE by construction).

The allowlist is MINIMAL and is never auto-expanded (§7):

    "покажи статус Hermes"
    "статус gateway"
    "состояние сервиса"
    "health Hermes"
    "gateway status"

Verified tool surface for an enforced STATUS_READ run (§8): the actual
current safe canary registry — ``runtime_status`` (primary) and
``canary_ping`` — READ_ONLY, local-only, no external endpoints.
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .capabilities import CapabilityRegistry
from .classifier import Classification
from .models import (
    EnforcementBlockReason,
    ExpectedSideEffect,
    IntentRisk,
    IntentType,
    RoutingRecommendation,
    SearchDenyReason,
    SearchSubtype,
    StatusSubtype,
)

#: EnforcementPolicy version string (reported in outcomes/telemetry).
ENFORCEMENT_POLICY_VERSION = "enforcement-v2"

#: The ONLY intent family that may ever be enforced in 1.2.0 (§1).
DEFAULT_ALLOWED_INTENTS: frozenset = frozenset({IntentType.STATUS_READ})

#: Default minimum confidence for an enforced route (§1).
DEFAULT_MIN_CONFIDENCE = 0.7

#: Risk classes compatible with a read-only enforced route.
_ENFORCE_ALLOWED_RISKS: frozenset = frozenset({IntentRisk.LOW})

#: Side effects compatible with an enforced read-only route (§1).
_ENFORCE_ALLOWED_SIDE_EFFECTS: frozenset = frozenset(
    {ExpectedSideEffect.NONE, ExpectedSideEffect.READ_ONLY}
)

#: Intent families that must NEVER be enforced (safety metric §12).
_UNSAFE_INTENTS: frozenset = frozenset({
    IntentType.WRITE_ACTION,
    IntentType.DELETE_ACTION,
    IntentType.SYSTEM_ACTION,
    IntentType.SCHEDULE_ACTION,
    IntentType.APPROVAL_ACTION,
    IntentType.UNKNOWN,
})

#: Minimal STATUS_READ allowlist (§7) — exact phrases, word-boundary
#: matched against the NORMALIZED request text. Sprint 1.2.1 §6
#: expanded it ONLY with unambiguous status phrases (RU + EN).
#: Never auto-expanded beyond explicit brief phrases.
STATUS_READ_ALLOWLIST: Tuple[str, ...] = (
    # ── Sprint 1.2.0 baseline (§7) ──────────────────────────────
    "покажи статус hermes",
    "статус gateway",
    "состояние сервиса",
    "health hermes",
    "gateway status",
    # ── Sprint 1.2.1 §6 RU ───────────────────────────────────────
    "статус hermes",
    "состояние gateway",
    "покажи health",
    "работает ли telegram",
    "статус scheduler",
    "какой сейчас provider",
    "состояние mcp",
    "покажи состояние runtime",
    # ── Sprint 1.2.1 §6 EN ───────────────────────────────────────
    "hermes status",
    "runtime health",
    "telegram status",
    "scheduler status",
    "provider status",
    "mcp status",
)

#: Sprint 1.2.1 §2 — deterministic STATUS_READ sub-intent markers.
#: First-match-wins, MOST SPECIFIC first (gateway > provider >
#: scheduler > integration > runtime > health > service). A marker
#: list hit maps the request to a subtype; no hit → GENERIC.
STATUS_SUBTYPE_MARKERS: Tuple[Tuple[StatusSubtype, Tuple[str, ...]], ...] = (
    (StatusSubtype.GATEWAY_STATUS, ("gateway",)),
    (StatusSubtype.PROVIDER_STATUS, ("provider", "провайдер")),
    (StatusSubtype.SCHEDULER_STATUS, ("scheduler", "cron", "крона")),
    (StatusSubtype.INTEGRATION_STATUS, ("telegram", "mcp", "интеграц")),
    (StatusSubtype.RUNTIME_STATUS, ("runtime", "рантайм")),
    (StatusSubtype.HEALTH_STATUS, ("health", "здоровь")),
    (StatusSubtype.SERVICE_STATUS, ("hermes", "сервис", "служб")),
)

#: Sprint 1.2.1 §4 — verified READ_ONLY tool surface per subtype.
#: Every value is a REAL registered tool name in the safe canary
#: registry (agent.gateway_v2.canary.default_canary_registry). The
#: gateway executes at most ONE tool per enforced run
#: (eligible_tools[0]); canary_ping is the shared fallback.
STATUS_SUBTYPE_TOOLS: Dict[str, Tuple[str, ...]] = {
    StatusSubtype.SERVICE_STATUS.value: ("runtime_status", "canary_ping"),
    StatusSubtype.GATEWAY_STATUS.value: ("gateway_status", "canary_ping"),
    StatusSubtype.RUNTIME_STATUS.value: ("runtime_status", "canary_ping"),
    StatusSubtype.HEALTH_STATUS.value: ("health_status", "canary_ping"),
    StatusSubtype.INTEGRATION_STATUS.value: (
        "integration_status", "canary_ping"),
    StatusSubtype.SCHEDULER_STATUS.value: ("scheduler_status", "canary_ping"),
    StatusSubtype.PROVIDER_STATUS.value: ("provider_status", "canary_ping"),
    StatusSubtype.GENERIC.value: ("runtime_status", "canary_ping"),
}

#: Sprint 1.2.1 §4 — the FULL verified enforced surface (union of
#: per-subtype primary tools + the shared fallback). All must exist
#: in the real canary registry AND carry the §5 metadata contract.
VERIFIED_STATUS_READ_TOOLS: Tuple[str, ...] = (
    "runtime_status",
    "gateway_status",
    "provider_status",
    "scheduler_status",
    "integration_status",
    "health_status",
    "canary_ping",
)

#: Sprint 1.2.1 §5 — READ-ONLY CONTRACT. Every enforced tool MUST
#: have side_effect=READ_ONLY + idempotent=true metadata in the real
#: registry. This table is the enforcement-side mirror of the canary
#: registry's ToolMetadata; a tool missing from it (or with wrong
#: metadata) → LEGACY (TOOL_METADATA gate).
STATUS_TOOL_METADATA: Dict[str, Dict[str, Any]] = {
    tool: {"side_effect": "READ_ONLY", "idempotent": True}
    for tool in VERIFIED_STATUS_READ_TOOLS
}

#: Sub-intent enforcement counters (§13) — per-subtype, all subtypes
#: of the STATUS_READ family.
STATUS_SUBTYPES: Tuple[str, ...] = tuple(
    s.value for s in StatusSubtype
)


def normalize_text(text: str) -> str:
    """Lowercase + collapse whitespace for allowlist matching."""
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _phrase_pattern(phrase: str) -> "re.Pattern[str]":
    return re.compile(rf"\b{re.escape(phrase)}\b")


#: Precompiled allowlist patterns (module-level, built once).
_ALLOWLIST_PATTERNS: List["re.Pattern[str]"] = [
    _phrase_pattern(p) for p in STATUS_READ_ALLOWLIST
]


def status_read_allowlist_matches(text: str) -> bool:
    """True when the normalized text matches ANY allowlist phrase (§7)."""
    norm = normalize_text(text)
    if not norm:
        return False
    return any(p.search(norm) for p in _ALLOWLIST_PATTERNS)


def detect_status_subtype(text: str) -> StatusSubtype:
    """Sprint 1.2.1 §2 — deterministic STATUS_READ sub-intent detection.

    First-match-wins over :data:`STATUS_SUBTYPE_MARKERS` (most
    specific first). A request with no marker hit → GENERIC. The
    result maps 1:1 to the per-subtype verified tool surface
    (:data:`STATUS_SUBTYPE_TOOLS`).
    """
    norm = normalize_text(str(text or ""))
    if not norm:
        return StatusSubtype.GENERIC
    for subtype, markers in STATUS_SUBTYPE_MARKERS:
        if any(_contains_word(norm, m) for m in markers):
            return subtype
    return StatusSubtype.GENERIC


def _contains_word(text: str, word: str) -> bool:
    """Word-boundary match (handles inflected/case variants via
    prefix-insensitive word lookup on the normalized text)."""
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


# ── Sprint 1.2.2 §16 — deterministic SEARCH_READ source detection ──
# Most-specific markers FIRST (same discipline as STATUS_SUBTYPE_
# MARKERS). A request with no marker → None → unsupported source
# (e.g. web search) → candidate V2 stays False.
SEARCH_SOURCE_MARKERS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("GATEWAY_LOG", ("ошибки gateway", "gateway errors", "gateway log",
                     "логи gateway", "лог gateway", "gateway лог",
                     "gateway logs", "логи gateway", "gateway",
                     "лог", "логи", "логги", "log")),
    ("EVENTS", ("события hermes", "события", "событий", "событие",
                "events", "event", "таймлайн", "timeline",
                "operations")),
    ("SCHEDULER", ("scheduler", "планировщик", "джоб", "джобы",
                   "job", "jobs", "cron", "задач", "задача")),
    ("PROVIDER", ("provider", "провайдер", "провайдера", "модель",
                  "model")),
    ("INTEGRATION", ("telegram", "mcp", "matrix", "feishu", "slack",
                     "discord", "integration", "интеграция",
                     "платформ", "бот", "bot")),
)

#: Markers that classify a search as NON-operational (web/general)
#: — a match here means unsupported source (candidate V2 stays
#: False, actual route LEGACY, §18 N6).
_WEB_SEARCH_MARKERS = (
    "в интернете", "internet", "статью", "статья", "документацию",
    "инструкцию", "новости", "news", "репозиторий", "repo",
    "github", "гитхаб",
)


def detect_search_source(text: str) -> Optional[str]:
    """Sprint 1.2.2 §16 — deterministic search source detection.

    Returns the SearchSource VALUE (e.g. ``"GATEWAY_LOG"``) or None
    when the request is not an operational search (web/general
    search → unsupported source). First-match-wins over
    :data:`SEARCH_SOURCE_MARKERS`; web markers are checked FIRST so
    a web search never grabs an operational source by accident.
    """
    norm = normalize_text(str(text or ""))
    if not norm:
        return None
    if any(_contains_word(norm, m) for m in _WEB_SEARCH_MARKERS):
        return None
    for source, markers in SEARCH_SOURCE_MARKERS:
        if any(_contains_word(norm, m) for m in markers):
            return source
    return None


#: Sprint 1.2.2 §3 — the verified search tool's READ-ONLY CONTRACT
#: (mirrors the canary registry metadata; the router checks THIS
#: table, never the live registry, so a registry drift cannot
#: silently widen the surface).
SEARCH_TOOL_METADATA: Dict[str, Dict[str, Any]] = {
    "operational_log_search": {
        "side_effect": "READ_ONLY",
        "idempotent": True,
        "network": False,
        "approval_required": False,
        "timeout": 2.0,
        "capabilities": ["OPERATIONAL_SEARCH", "LOG_SEARCH",
                         "EVENT_SEARCH"],
        "sources": ["GATEWAY_LOG", "EVENTS", "SCHEDULER",
                    "PROVIDER", "INTEGRATION"],
    },
}
#: Verified search tool names (the ONLY tools that may satisfy a
#: SEARCH_READ candidate; §3 — registered in the verified registry
#: only).
VERIFIED_SEARCH_TOOLS: Tuple[str, ...] = ("operational_log_search",)


def search_tool_metadata_ok(tool: str) -> bool:
    """Sprint 1.2.2 §3/§5 — search tool READ-ONLY contract check.

    True only when the tool is the verified search tool with
    READ_ONLY + idempotent + no-network metadata. Any other state →
    False → candidate V2 stays False (fail closed).
    """
    meta = SEARCH_TOOL_METADATA.get(tool)
    if not meta:
        return False
    return (
        meta.get("side_effect") == "READ_ONLY"
        and bool(meta.get("idempotent"))
        and not bool(meta.get("network"))
    )


def tool_metadata_ok(tool: str) -> bool:
    """Sprint 1.2.1 §5 — READ-ONLY CONTRACT check.

    True only when the tool is listed in :data:`STATUS_TOOL_METADATA`
    with side_effect=READ_ONLY AND idempotent=true. Any other state
    (missing / wrong side effect / not idempotent) → False → the
    policy blocks enforcement for that tool (LEGACY).
    """
    meta = STATUS_TOOL_METADATA.get(tool)
    if not meta:
        return False
    return (
        meta.get("side_effect") == "READ_ONLY"
        and bool(meta.get("idempotent"))
    )


# ══════════════════════════════════════════════════════════════════
# Sprint 1.2.3 — SEARCH_READ CONTROLLED CANARY (§1-§18)
# ══════════════════════════════════════════════════════════════════

#: Sprint 1.2.3 §9 — the controlled-canary allowlist. EXACT phrases,
#: word-boundary matched against the NORMALIZED request text (§10).
#: Never auto-expanded beyond the brief's list.
SEARCH_CANARY_ALLOWLIST: Tuple[str, ...] = (
    # ── §9 RU ─────────────────────────────────────────────────────
    "найди последние ошибки gateway",
    "покажи события hermes за последний час",
    "найди ошибки scheduler",
    "покажи последние provider errors",
    "найди ошибки telegram",
    "последние ошибки mcp",
    # ── §9 EN ─────────────────────────────────────────────────────
    "find recent gateway errors",
    "show recent hermes events",
    "find scheduler errors",
    "show provider errors",
    "find telegram errors",
    "show mcp errors",
)

#: Sprint 1.2.4 §12 — the LIVE (limited-production) allowlist.
#: The brief's "initial production phrases" — NOT identical to the
#: canary list (3 RU phrases differ: «покажи последние события
#: Hermes», «покажи последние ошибки provider», «покажи ошибки
#: MCP»). EXACT phrases, word-boundary matched against the
#: NORMALIZED request text. No auto-expansion.
SEARCH_PROD_ALLOWLIST: Tuple[str, ...] = (
    # ── §12 RU ────────────────────────────────────────────────────
    "найди последние ошибки gateway",
    "покажи последние события hermes",
    "найди ошибки scheduler",
    "покажи последние ошибки provider",
    "найди ошибки telegram",
    "покажи ошибки mcp",
    # ── §12 EN ────────────────────────────────────────────────────
    "find recent gateway errors",
    "show recent hermes events",
    "find scheduler errors",
    "show provider errors",
    "find telegram errors",
    "show mcp errors",
)

#: Sprint 1.2.3 §2/§3 — the ONLY canary-allowed search subtypes and
#: their 1:1 deterministic sources.
SEARCH_ALLOWED_SUBTYPES: Tuple[str, ...] = tuple(
    s.value for s in SearchSubtype
)
SEARCH_ALLOWED_SOURCES: frozenset = frozenset({
    "GATEWAY_LOG", "EVENTS", "SCHEDULER", "PROVIDER", "INTEGRATION",
})
SEARCH_SUBTYPE_BY_SOURCE: Dict[str, str] = {
    "GATEWAY_LOG": SearchSubtype.LOG_SEARCH.value,
    "EVENTS": SearchSubtype.EVENT_SEARCH.value,
    "SCHEDULER": SearchSubtype.SCHEDULER_SEARCH.value,
    "PROVIDER": SearchSubtype.PROVIDER_SEARCH.value,
    "INTEGRATION": SearchSubtype.INTEGRATION_SEARCH.value,
}

#: Sprint 1.2.3 §18 — the initial enforced sample cap: at most this
#: many SUCCESSFUL live V2 search runs. Synthetic samples never
#: count (§19). After the cap the canary keeps the flag but stops
#: granting new V2 search routes (LEGACY) — no auto-expansion.
SEARCH_CANARY_MAX_SUCCESS = 20

#: Sprint 1.2.4 §11 — the LIMITED PRODUCTION validation sample cap:
#: at most this many SUCCESSFUL live SEARCH_READ V2 executions during
#: the sprint validation window. Synthetic samples never count. After
#: the cap the production mode keeps running but stops granting new
#: V2 search routes (LEGACY, deny reason SEARCH_LIMIT_REACHED).
SEARCH_PROD_MAX_SUCCESS = 50

#: Sprint 1.2.3 §7 — deterministic mixed-intent safety net. Substring
#: check on the NORMALIZED text (aggressive → fail closed to LEGACY).
#: Unsafe intent ALWAYS outranks SEARCH_READ; this detector catches
#: a SEARCH_READ classification whose text ALSO carries a
#: write/delete/system/schedule/approval action word.
_UNSAFE_ACTION_WORDS: Tuple[str, ...] = (
    # ru
    "удал", "стер", "перезапуст", "рестарт", "перезагруз",
    "создай", "создат", "переключ", "измен", "отправ", "запис",
    "сохран", "выполн", "установ", "отключ", "включ", "добавь",
    "обнов", "деактив", "монтируй", "загрузи", "скачай", "почист",
    "очист", "стоп", "останов", "запусти", "запустить", "исправь",
    "казни", "заблокир", "удали",
    # en
    "delete", "remove", "restart", "reboot", "create", "switch",
    "change", "send", "write", "save", "execute", "install", "stop",
    "start", "kill", "update", "modify", "disable", "enable", "add",
    "run", "launch", "clean", "purge", "erase", "fix", "drop",
)

#: Precompiled canary allowlist patterns (module-level, built once).
_SEARCH_CANARY_PATTERNS: List["re.Pattern[str]"] = [
    _phrase_pattern(p) for p in SEARCH_CANARY_ALLOWLIST
]

#: Precompiled production allowlist patterns (Sprint 1.2.4 §12).
_SEARCH_PROD_PATTERNS: List["re.Pattern[str]"] = [
    _phrase_pattern(p) for p in SEARCH_PROD_ALLOWLIST
]


def search_canary_allowlist_matches(text: str) -> bool:
    """Sprint 1.2.3 §9/§10 — allowlist check on the NORMALIZED text."""
    norm = normalize_text(text)
    if not norm:
        return False
    return any(p.search(norm) for p in _SEARCH_CANARY_PATTERNS)


def search_prod_allowlist_matches(text: str) -> bool:
    """Sprint 1.2.4 §12 — LIVE allowlist check on the NORMALIZED
    text. Exact phrases only; no auto-expansion."""
    norm = normalize_text(text)
    if not norm:
        return False
    return any(p.search(norm) for p in _SEARCH_PROD_PATTERNS)


def detect_search_subtype(text: str) -> Optional[str]:
    """Sprint 1.2.3 §2 — deterministic SEARCH_READ subtype detection.

    Maps a detected operational source to its 1:1 verified subtype
    (LOG_SEARCH ← GATEWAY_LOG, EVENT_SEARCH ← EVENTS, ...). An
    unsupported/missing source → None → subtype gate denies.
    """
    source = detect_search_source(text)
    if source is None:
        return None
    return SEARCH_SUBTYPE_BY_SOURCE.get(source)


def has_mixed_unsafe_intent(text: str) -> bool:
    """Sprint 1.2.3 §7 — unsafe intent always beats SEARCH_READ.

    Deterministic substring scan of the normalized text for unsafe
    action words. Conservative (substring, broad verb list) → any hit
    fails closed to LEGACY. The canary allowlist phrases themselves
    contain none of these words (verified at build time in tests).
    """
    norm = normalize_text(text)
    if not norm:
        return False
    return any(w in norm for w in _UNSAFE_ACTION_WORDS)


def _search_gate_ladder(
    *,
    policy_enabled: bool,
    min_confidence: float,
    max_success_live: int,
    allowlist_fn,
    classification: Classification,
    text: str,
    health: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None,
    subtype: Optional[str] = None,
    tool_verified: bool = False,
    query_ok: bool = True,
    secret_query: bool = False,
    health_ok: bool = True,
    confidence_ok: bool = True,
    missing_capabilities: Optional[List[str]] = None,
    live: bool = True,
    success_live: int = 0,
    cap_reason: str = SearchDenyReason.CANARY_LIMIT_REACHED.value,
    cap_code: str = "search_canary_limit_reached",
    allowed_code: str = "search_canary_allowed",
) -> Tuple[bool, Optional[str], List[str]]:
    """Shared SEARCH_READ gate ladder (Sprint 1.2.3 §1-§18 + 1.2.4 §1-§16).

    Deterministic ordered gates, fail closed. Used by BOTH the
    controlled canary policy (``cap_reason=CANARY_LIMIT_REACHED``,
    ``allowed_code=search_canary_allowed``) and the limited-production
    policy (``cap_reason=SEARCH_LIMIT_REACHED``,
    ``allowed_code=search_prod_allowed``). The order and deny reasons
    are a hard contract — never reorder or rename without re-running
    the full canary/prod/shadow test files.

    Returns ``(allowed, deny_reason, reason_codes)``. ``text`` is the
    NORMALIZED request text (never persisted) — used only for the
    allowlist + mixed-intent checks.
    """
    if not policy_enabled:
        return (
            False, SearchDenyReason.POLICY_DISABLED.value,
            ["search_policy_disabled"],
        )

    # 1) intent must be SEARCH_READ (defensive; caller routes
    #    only SEARCH_READ here) — unsafe intents NEVER reach V2.
    if classification.intent is not IntentType.SEARCH_READ:
        return (
            False, SearchDenyReason.SEARCH_NOT_ALLOWLISTED.value,
            ["search_intent_not_allowed"],
        )

    # 2) mixed unsafe intent (§7) — unsafe always stronger.
    if has_mixed_unsafe_intent(str(text or "")):
        return (
            False, SearchDenyReason.UNSAFE_MIXED_INTENT.value,
            ["search_mixed_unsafe_intent"],
        )

    # 3) secret query — NEVER V2 (§8), tool execution = 0. Checked
    #    BEFORE the allowlist so a secret-hunting phrase always
    #    reports SECRET_QUERY (never the allowlist reason).
    if secret_query:
        return (
            False, SearchDenyReason.SECRET_QUERY.value,
            ["search_secret_query"],
        )

    # 4) allowlist (§9/§12) — normalized request must match a phrase.
    if not allowlist_fn(str(text or "")):
        return (
            False, SearchDenyReason.SEARCH_NOT_ALLOWLISTED.value,
            ["search_not_allowlisted"],
        )

    # 5) subtype ∈ verified subtypes (§2).
    if subtype is None or subtype not in SEARCH_ALLOWED_SUBTYPES:
        return (
            False, SearchDenyReason.SEARCH_NOT_ALLOWLISTED.value,
            ["search_subtype_not_allowed"],
        )

    # 6) source allowlisted (§3).
    if source is None or source not in SEARCH_ALLOWED_SOURCES:
        return (
            False, SearchDenyReason.SOURCE_NOT_ALLOWED.value,
            ["search_source_not_allowed"],
        )

    # 7) capability OPERATIONAL_SEARCH verified (§1).
    missing = list(missing_capabilities or [])
    if missing:
        return (
            False, SearchDenyReason.CAPABILITY_MISSING.value,
            ["search_missing_capability"],
        )

    # 8) tool verified — READ_ONLY + idempotent + no-network (§1).
    if not tool_verified:
        return (
            False, SearchDenyReason.TOOL_NOT_VERIFIED.value,
            ["search_tool_not_verified"],
        )

    # 9) query valid (§10) — normalized, bounded, non-empty.
    if not query_ok:
        return (
            False, SearchDenyReason.QUERY_INVALID.value,
            ["search_invalid_query"],
        )

    # 10) health == HEALTHY (§1).
    if not health_ok:
        return (
            False, SearchDenyReason.HEALTH_UNAVAILABLE.value,
            ["search_health_unavailable"],
        )

    # 11) confidence >= threshold (§1).
    if not confidence_ok:
        return (
            False, SearchDenyReason.LOW_CONFIDENCE.value,
            ["search_low_confidence"],
        )

    # 12) no ambiguity (§1).
    lexical = getattr(classification, "lexical_hits", None)
    if isinstance(lexical, (list, tuple)) and "ambiguous" in lexical:
        return (
            False, SearchDenyReason.AMBIGUOUS.value,
            ["search_ambiguous"],
        )

    # 13) sample cap (§18 canary / §11 production) — LIVE only.
    if live and success_live >= max_success_live:
        return (
            False, cap_reason,
            [cap_code],
        )

    return True, None, [allowed_code]


class SearchCanaryPolicy:
    """Sprint 1.2.3 §6 — scoped SEARCH_READ canary policy.

    Decision: ALLOW_V2_SEARCH (grant the V2 canary route for the
    verified ``operational_log_search`` tool) or LEGACY with a
    mandatory deny reason (§6). The policy is PURE — it evaluates
    and returns (allowed, deny_reason, reason_codes); it never
    executes tools.

    Enforcement scope (§1) — ALLOW only when EVERY gate passes:
    intent == SEARCH_READ, subtype ∈ verified subtypes, capability
    OPERATIONAL_SEARCH verified, tool == operational_log_search with
    the READ-ONLY metadata contract, query safe (valid + not secret),
    source allowlisted, confidence >= threshold, health HEALTHY, no
    ambiguity, no mixed unsafe intent, allowlist phrase matched, and
    the canary sample cap not reached. ANY failure → LEGACY.
    """

    VERSION = "search-canary-v1"

    def __init__(
        self,
        enabled: bool = True,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        max_success_live: int = SEARCH_CANARY_MAX_SUCCESS,
        allowlist_fn=None,
    ) -> None:
        self.enabled = bool(enabled)
        self.min_confidence = float(min_confidence)
        self.max_success_live = int(max_success_live)
        self._allowlist = (
            allowlist_fn or search_canary_allowlist_matches)

    # ── evaluation ──────────────────────────────────────────────────

    def decide(
        self,
        classification: Classification,
        text: str,
        health: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
        subtype: Optional[str] = None,
        tool_verified: bool = False,
        query_ok: bool = True,
        secret_query: bool = False,
        health_ok: bool = True,
        confidence_ok: bool = True,
        missing_capabilities: Optional[List[str]] = None,
        live: bool = True,
        success_live: int = 0,
    ) -> Tuple[bool, Optional[str], List[str]]:
        """(allowed, deny_reason, reason_codes).

        Ordered gate ladder — mixed unsafe intent and the allowlist
        gate run BEFORE the capability/tool gates (a non-allowlisted
        request must never reach the verified surface). ``text`` is
        the NORMALIZED request text (never persisted, §10); it is
        used only for the allowlist + mixed-intent checks. The
        ladder itself is shared with the Sprint 1.2.4 production
        policy (:func:`_search_gate_ladder`).
        """
        return _search_gate_ladder(
            policy_enabled=self.enabled,
            min_confidence=self.min_confidence,
            max_success_live=self.max_success_live,
            allowlist_fn=self._allowlist,
            classification=classification,
            text=text,
            health=health,
            source=source,
            subtype=subtype,
            tool_verified=tool_verified,
            query_ok=query_ok,
            secret_query=secret_query,
            health_ok=health_ok,
            confidence_ok=confidence_ok,
            missing_capabilities=missing_capabilities,
            live=live,
            success_live=success_live,
            cap_reason=SearchDenyReason.CANARY_LIMIT_REACHED.value,
            cap_code="search_canary_limit_reached",
            allowed_code="search_canary_allowed",
        )

    def summary(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "version": self.VERSION,
            "min_confidence": self.min_confidence,
            "max_success_live": self.max_success_live,
            "allowlist": list(SEARCH_CANARY_ALLOWLIST),
            "allowed_subtypes": list(SEARCH_ALLOWED_SUBTYPES),
            "allowed_sources": sorted(SEARCH_ALLOWED_SOURCES),
            "tool": "operational_log_search",
        }


class SearchProductionPolicy:
    """Sprint 1.2.4 §1-§16 — SEARCH_READ LIMITED PRODUCTION policy.

    Decision: ALLOW_V2_SEARCH (grant the production V2 route for the
    verified ``operational_log_search`` tool, actual route ``V2``,
    §9) or LEGACY with a mandatory deny reason (§16). The policy is
    PURE — it evaluates and returns (allowed, deny_reason,
    reason_codes); it never executes tools.

    Enforcement scope (§1) — ALLOW only when EVERY gate passes
    (identical ladder to the canary policy, :func:`_search_gate_ladder`):
    intent == SEARCH_READ, subtype ∈ the five verified subtypes,
    capability OPERATIONAL_SEARCH verified, tool ==
    operational_log_search with the READ-ONLY metadata contract,
    query safe (valid + not secret), source allowlisted, confidence
    >= threshold, health HEALTHY, no ambiguity, no mixed unsafe
    intent (§6), allowlist phrase matched (§12 — no auto-expansion),
    and the production sample cap (§11, 50 live) not reached.

    Differences from the canary policy: production version string,
    cap deny reason SEARCH_LIMIT_REACHED, allowed code
    ``search_prod_allowed`` — everything else is the shared ladder.
    """

    VERSION = "search-prod-v1"

    def __init__(
        self,
        enabled: bool = True,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        max_success_live: int = SEARCH_PROD_MAX_SUCCESS,
        allowlist_fn=None,
    ) -> None:
        self.enabled = bool(enabled)
        self.min_confidence = float(min_confidence)
        self.max_success_live = int(max_success_live)
        # §12 — the LIVE allowlist is the brief's own 12 production
        # phrases (SEARCH_PROD_ALLOWLIST; NOT the canary list — 3 RU
        # phrases differ). Never expanded.
        self._allowlist = (
            allowlist_fn or search_prod_allowlist_matches)

    # ── evaluation ──────────────────────────────────────────────────

    def decide(
        self,
        classification: Classification,
        text: str,
        health: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
        subtype: Optional[str] = None,
        tool_verified: bool = False,
        query_ok: bool = True,
        secret_query: bool = False,
        health_ok: bool = True,
        confidence_ok: bool = True,
        missing_capabilities: Optional[List[str]] = None,
        live: bool = True,
        success_live: int = 0,
    ) -> Tuple[bool, Optional[str], List[str]]:
        """(allowed, deny_reason, reason_codes) — shared gate ladder.

        ``text`` is the NORMALIZED request text (never persisted);
        it is used only for the allowlist + mixed-intent checks.
        """
        return _search_gate_ladder(
            policy_enabled=self.enabled,
            min_confidence=self.min_confidence,
            max_success_live=self.max_success_live,
            allowlist_fn=self._allowlist,
            classification=classification,
            text=text,
            health=health,
            source=source,
            subtype=subtype,
            tool_verified=tool_verified,
            query_ok=query_ok,
            secret_query=secret_query,
            health_ok=health_ok,
            confidence_ok=confidence_ok,
            missing_capabilities=missing_capabilities,
            live=live,
            success_live=success_live,
            cap_reason=SearchDenyReason.SEARCH_LIMIT_REACHED.value,
            cap_code="search_prod_limit_reached",
            allowed_code="search_prod_allowed",
        )

    def summary(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "version": self.VERSION,
            "min_confidence": self.min_confidence,
            "max_success_live": self.max_success_live,
            "allowlist": list(SEARCH_PROD_ALLOWLIST),
            "allowed_subtypes": list(SEARCH_ALLOWED_SUBTYPES),
            "allowed_sources": sorted(SEARCH_ALLOWED_SOURCES),
            "tool": "operational_log_search",
            "route": "V2",
        }


class EnforcementPolicy:
    """Explicit enforcement policy object (Sprint 1.2.0 §4).

    Fields:

    - ``enabled`` — master switch of the policy object (the router
      mode gate is handled by the caller: enforcement runs only in
      ``enforce_status_read`` mode).
    - ``allowed_intents`` — the ONLY intents that may be enforced.
    - ``min_confidence`` — confidence threshold for the enforced route.
    - ``require_health`` — block unless runtime health == HEALTHY.
    - ``require_capabilities`` — block unless required capabilities
      are fully verified.
    - ``require_internal_allowlist`` — block unless the request text
      passes the STATUS_READ allowlist.
    - ``fallback_route`` — where a denied attempt goes (LEGACY).

    Defaults: allowed_intents={STATUS_READ}, fallback_route=LEGACY.
    The policy is PURE: it evaluates and returns (allowed, block_reason,
    reason_codes) — it never executes, switches or calls tools.
    """

    VERSION = ENFORCEMENT_POLICY_VERSION

    def __init__(
        self,
        enabled: bool = True,
        allowed_intents: Optional[Iterable[IntentType]] = None,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        require_health: bool = True,
        require_capabilities: bool = True,
        require_internal_allowlist: bool = True,
        require_tool_metadata: bool = True,
        fallback_route: str = RoutingRecommendation.LEGACY.value,
        capabilities: Optional[CapabilityRegistry] = None,
        allowlist_fn=None,
    ) -> None:
        self.enabled = bool(enabled)
        self.allowed_intents: frozenset = frozenset(
            allowed_intents if allowed_intents is not None
            else DEFAULT_ALLOWED_INTENTS
        )
        self.min_confidence = float(min_confidence)
        self.require_health = bool(require_health)
        self.require_capabilities = bool(require_capabilities)
        self.require_internal_allowlist = bool(
            require_internal_allowlist
        )
        # Sprint 1.2.1 §5 — READ-ONLY CONTRACT gate.
        self.require_tool_metadata = bool(require_tool_metadata)
        self.fallback_route = fallback_route or \
            RoutingRecommendation.LEGACY.value
        self._capabilities = capabilities or CapabilityRegistry()
        self._allowlist = allowlist_fn or status_read_allowlist_matches

    # ── evaluation ──────────────────────────────────────────────────

    def evaluate(
        self,
        classification: Classification,
        text: str,
        health: Optional[Dict[str, Any]] = None,
        status_subtype: Optional[StatusSubtype] = None,
    ) -> Tuple[bool, Optional[str], List[str]]:
        """(allowed, block_reason, reason_codes).

        Ordered gate ladder, intent-family FIRST (proven disposition
        precedence, Sprint 1.1.1.1): the intent allowlist decides
        before any side-effect/risk consideration — an unsafe intent
        can never reach the read-only branch. ``text`` is the raw
        request text (used ONLY for allowlist matching; it never
        enters the outcome). ``status_subtype`` (Sprint 1.2.1 §2/§5)
        selects the per-subtype verified tool surface; its primary
        tool must satisfy the READ-ONLY metadata contract.
        """
        if not self.enabled:
            return (
                False, EnforcementBlockReason.POLICY.value,
                ["enforcement_disabled"],
            )
        health = health or {}

        # 1) intent family — hard gate (unsafe intents can NEVER pass,
        #    even with side_effect=none/read_only).
        intent = classification.intent
        if intent in _UNSAFE_INTENTS:
            return (
                False, EnforcementBlockReason.INTENT_NOT_ALLOWED.value,
                ["intent_not_allowed"],
            )
        if intent not in self.allowed_intents:
            return (
                False, EnforcementBlockReason.INTENT_NOT_ALLOWED.value,
                ["intent_not_allowed"],
            )

        # 2) risk grade must be read-only compatible.
        if classification.risk not in _ENFORCE_ALLOWED_RISKS:
            return (
                False, EnforcementBlockReason.POLICY.value,
                ["risk_not_read_only"],
            )

        # 3) expected side effect must be none/read-only.
        if classification.expected_side_effect \
                not in _ENFORCE_ALLOWED_SIDE_EFFECTS:
            return (
                False, EnforcementBlockReason.POLICY.value,
                ["unsafe_side_effect"],
            )

        # 4) confidence threshold (§1).
        if classification.confidence is None or \
                classification.confidence < self.min_confidence:
            return (
                False, EnforcementBlockReason.LOW_CONFIDENCE.value,
                ["low_confidence"],
            )

        # 5) capabilities fully verified (§1).
        if self.require_capabilities:
            required = self._capabilities.required_for(intent)
            if not required or not \
                    self._capabilities.capabilities_satisfied(required):
                return (
                    False, EnforcementBlockReason.CAPABILITY.value,
                    ["capability_missing"],
                )

        # 6) runtime/provider health == HEALTHY (§1).
        if self.require_health and health.get("status", "unknown") \
                != "healthy":
            return (
                False, EnforcementBlockReason.HEALTH.value,
                ["health_gate"],
            )

        # 7) request passes the internal STATUS_READ allowlist (§1/§7).
        if self.require_internal_allowlist:
            if not self._allowlist(str(text or "")):
                return (
                    False, EnforcementBlockReason.ALLOWLIST.value,
                    ["allowlist_required"],
                )

        # 8) Sprint 1.2.1 §5 — the per-subtype primary tool must carry
        #    READ_ONLY + idempotent metadata. Unknown/mutating/missing
        #    metadata → LEGACY (fail closed).
        if self.require_tool_metadata:
            subtype = status_subtype or detect_status_subtype(text)
            primary = STATUS_SUBTYPE_TOOLS.get(
                subtype.value, ("runtime_status",))[0]
            if not tool_metadata_ok(primary):
                return (
                    False, EnforcementBlockReason.TOOL_METADATA.value,
                    ["tool_metadata_missing"],
                )

        # 9) no approval required, no ambiguity (§1) — STATUS_READ is
        #    unambiguous by construction; both are defensive.
        if getattr(classification, "approval_required", False):
            return (
                False, EnforcementBlockReason.APPROVAL.value,
                ["approval_required"],
            )
        ambiguous = getattr(classification, "lexical_hits", None)
        if isinstance(ambiguous, (list, tuple)) and "ambiguous" in \
                ambiguous:
            return (
                False, EnforcementBlockReason.AMBIGUOUS.value,
                ["ambiguous"],
            )

        return True, None, ["status_read_enforced"]

    # ── surface ─────────────────────────────────────────────────────

    def eligible_tools(
        self, status_subtype: Optional[StatusSubtype] = None,
    ) -> List[str]:
        """Verified READ_ONLY tool surface for an enforced run (§4/§8).

        Sprint 1.2.1 §2: per-subtype surface — the subtype's primary
        tool first, ``canary_ping`` as the shared fallback. The
        gateway executes at most ONE tool (eligible_tools[0]).
        """
        if status_subtype is None:
            return list(VERIFIED_STATUS_READ_TOOLS)
        return list(STATUS_SUBTYPE_TOOLS.get(
            status_subtype.value, ("runtime_status", "canary_ping")))

    def summary(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "allowed_intents": sorted(
                i.value for i in self.allowed_intents
            ),
            "min_confidence": self.min_confidence,
            "require_health": self.require_health,
            "require_capabilities": self.require_capabilities,
            "require_internal_allowlist": self.require_internal_allowlist,
            "require_tool_metadata": self.require_tool_metadata,
            "fallback_route": self.fallback_route,
            "verified_tools": list(VERIFIED_STATUS_READ_TOOLS),
            "allowlist": list(STATUS_READ_ALLOWLIST),
            "subtype_tools": {
                k: list(v) for k, v in STATUS_SUBTYPE_TOOLS.items()
            },
        }


__all__ = [
    "EnforcementPolicy",
    "EnforcementBlockReason",
    "STATUS_READ_ALLOWLIST",
    "VERIFIED_STATUS_READ_TOOLS",
    "STATUS_SUBTYPE_MARKERS",
    "STATUS_SUBTYPE_TOOLS",
    "STATUS_TOOL_METADATA",
    "STATUS_SUBTYPES",
    "DEFAULT_ALLOWED_INTENTS",
    "DEFAULT_MIN_CONFIDENCE",
    "ENFORCEMENT_POLICY_VERSION",
    "normalize_text",
    "status_read_allowlist_matches",
    "detect_status_subtype",
    "tool_metadata_ok",
    # Sprint 1.2.2
    "detect_search_source",
    "SEARCH_SOURCE_MARKERS",
    "SEARCH_TOOL_METADATA",
    "VERIFIED_SEARCH_TOOLS",
    "search_tool_metadata_ok",
    # Sprint 1.2.3
    "SearchCanaryPolicy",
    "SEARCH_CANARY_ALLOWLIST",
    "SEARCH_ALLOWED_SUBTYPES",
    "SEARCH_ALLOWED_SOURCES",
    "SEARCH_SUBTYPE_BY_SOURCE",
    "SEARCH_CANARY_MAX_SUCCESS",
    "search_canary_allowlist_matches",
    "detect_search_subtype",
    "has_mixed_unsafe_intent",
    # Sprint 1.2.4
    "SearchProductionPolicy",
    "SEARCH_PROD_MAX_SUCCESS",
    "SEARCH_PROD_ALLOWLIST",
    "search_prod_allowlist_matches",
    "_search_gate_ladder",
]
